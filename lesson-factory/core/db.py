"""버스 DB. 지금 쓰는 것은 `llm_calls` 와 `artifacts` 두 표뿐이다.

상태기계(`jobs`·`messages`)는 P2 에서 붙지만 스키마는 미리 만들어 둔다 — 나중에
표를 새로 만들면 그전 기록이 남지 않아서, 첫 호출부터 같은 자리에 쌓이게 하는 편이 낫다.

CLAUDE.md B-4: **모든 LLM 호출의 모델·토큰·비용을 기록한다.**
CLAUDE.md B-5: 산출물은 DB + 파일 이중 기록한다.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "lesson_factory.sqlite"
PRICES = ROOT / "contracts" / "model_prices.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY, trace_id TEXT NOT NULL, kind TEXT NOT NULL,
    state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0, max_attempt INTEGER NOT NULL DEFAULT 3,
    payload_ref TEXT, claimed_by TEXT, lease_until TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, trace_id TEXT NOT NULL, ts TEXT NOT NULL,
    sender TEXT, recipient TEXT, type TEXT, payload_ref TEXT, note TEXT);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY, trace_id TEXT NOT NULL, kind TEXT NOT NULL,
    path TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
    sha256 TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS verdicts (
    id INTEGER PRIMARY KEY, trace_id TEXT NOT NULL, attempt INTEGER NOT NULL,
    result TEXT NOT NULL, json_ref TEXT, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY, trace_id TEXT NOT NULL, agent TEXT NOT NULL,
    model TEXT NOT NULL, effort TEXT,
    in_tokens INTEGER NOT NULL DEFAULT 0, out_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0, cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL, stop_reason TEXT, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY, trace_id TEXT NOT NULL, taught_at TEXT,
    timing_ok TEXT, engagement INTEGER, what_worked TEXT, what_failed TEXT,
    created_at TEXT NOT NULL);

CREATE INDEX IF NOT EXISTS idx_llm_calls_trace ON llm_calls(trace_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_trace ON artifacts(trace_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DEFAULT_DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ------------------------------------------------------------------------ 비용

def load_prices(path: Path | None = None) -> dict:
    return json.loads((path or PRICES).read_text(encoding="utf-8"))["per_million"]


def cost_usd(model: str, in_tokens: int, out_tokens: int, prices: dict | None = None) -> float | None:
    """단가표에 없는 모델이면 **None**. 0 이 아니다.

    0 을 돌려주면 '공짜로 돌았다' 와 '얼마인지 모른다' 가 같은 값이 되고, 비용 상한이
    조용히 무력해진다. 모르는 것은 모른다고 적는다.
    """
    table = (prices if prices is not None else load_prices()).get(model)
    if not table:
        return None
    return in_tokens / 1_000_000 * table["input"] + out_tokens / 1_000_000 * table["output"]


def record_llm_call(conn: sqlite3.Connection, **row) -> int:
    row.setdefault("created_at", now())
    columns = ", ".join(row)
    holders = ", ".join("?" for _ in row)
    cur = conn.execute(f"INSERT INTO llm_calls ({columns}) VALUES ({holders})", tuple(row.values()))
    conn.commit()
    return int(cur.lastrowid)


def spent_usd(conn: sqlite3.Connection, trace_id: str) -> float:
    """이 작업에 지금까지 쓴 돈. 단가를 모르는 호출은 0 으로 세지 않고 제외한다."""
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM llm_calls WHERE trace_id = ? AND cost_usd IS NOT NULL",
        (trace_id,),
    ).fetchone()
    return float(row["total"])


def record_artifact(conn: sqlite3.Connection, trace_id: str, kind: str, path: Path, version: int = 1) -> int:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    cur = conn.execute(
        "INSERT INTO artifacts (trace_id, kind, path, version, sha256, created_at) VALUES (?,?,?,?,?,?)",
        (trace_id, kind, str(path), version, digest, now()),
    )
    conn.commit()
    return int(cur.lastrowid)
