#!/usr/bin/env python3
"""NCIC 2022 개정 성취기준 xlsx → curriculum/standards.sqlite

CLAUDE.md B-1: 성취기준은 이 DB 조회로만 사용한다. 조회 실패는 작업 실패다.
모델이 성취기준을 지어내는 것을 원천 차단하기 위한 유일한 근거 자료.

표준 라이브러리만 쓴다 (xlsx = zip + XML). openpyxl 불필요.
재실행해도 결과가 같다 (멱등).

사용법:
    python3 scripts/seed_standards.py
    python3 scripts/seed_standards.py --xlsx <경로> --db <경로>
    python3 scripts/seed_standards.py --check 6사05-02
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XLSX = ROOT / "curriculum" / "source" / "NCIC_2022_초등_전과목_성취기준.xlsx"
DEFAULT_DB = ROOT / "curriculum" / "standards.sqlite"

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
SHEET_NAME = "전체 성취기준"

# 열 순서는 파일 헤더에서 읽어 매핑한다. 위치를 가정하지 않는다.
COLUMN_MAP = {
    "교육과정": "curriculum",
    "학교급": "school_level",
    "학년군": "grade_band",
    "과목": "subject",
    "성취기준코드": "code_raw",
    "영역코드": "area_code",
    "성취기준": "text",
    "NCIC인벤토리번호": "ncic_id",
    "확인기준": "basis",
    "출처URL": "source_url",
}

DDL = """
CREATE TABLE IF NOT EXISTS standards (
    code         TEXT PRIMARY KEY,   -- '6사05-02' (대괄호 제거한 정규형)
    code_raw     TEXT NOT NULL,      -- '[6사05-02]' (원본 표기 보존)
    curriculum   TEXT,
    school_level TEXT,
    grade_band   TEXT,
    subject      TEXT,
    area_code    TEXT,
    text         TEXT NOT NULL,
    ncic_id      TEXT,
    basis        TEXT,
    source_url   TEXT,
    imported_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_standards_subject_band
    ON standards(subject, grade_band);
"""


def _cell_text(cell: ET.Element) -> str | None:
    """<c> 요소에서 값을 뽑는다. 이 파일은 inline string 을 쓴다."""
    inline = cell.find(f"{NS}is")
    if inline is not None:
        return "".join(t.text or "" for t in inline.iter(f"{NS}t"))
    v = cell.find(f"{NS}v")
    return v.text if v is not None else None


def _sheet_path(zf: zipfile.ZipFile, sheet_name: str) -> str:
    """워크북에서 시트 이름 → xl/worksheets/sheetN.xml 경로를 찾는다."""
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    names = [s.get("name") for s in wb.iter(f"{NS}sheet")]
    if sheet_name not in names:
        raise SystemExit(f"시트 '{sheet_name}' 없음. 있는 시트: {names}")
    idx = names.index(sheet_name) + 1
    path = f"xl/worksheets/sheet{idx}.xml"
    if path not in zf.namelist():
        raise SystemExit(f"{path} 없음")
    return path


def read_rows(xlsx: Path) -> list[dict[str, str]]:
    """시트를 헤더 기준 dict 리스트로 읽는다."""
    with zipfile.ZipFile(xlsx) as zf:
        root = ET.fromstring(zf.read(_sheet_path(zf, SHEET_NAME)))

    raw: list[dict[str, str | None]] = []
    for row in root.iter(f"{NS}row"):
        cells: dict[str, str | None] = {}
        for c in row.findall(f"{NS}c"):
            ref = c.get("r") or ""
            m = re.match(r"[A-Z]+", ref)
            if m:
                cells[m.group()] = _cell_text(c)
        raw.append(cells)

    if not raw:
        raise SystemExit("빈 시트")

    header = {col: (name or "").strip() for col, name in raw[0].items()}
    unknown = set(header.values()) - set(COLUMN_MAP) - {""}
    if unknown:
        print(f"  경고: 모르는 열 무시 — {sorted(unknown)}", file=sys.stderr)

    out = []
    for cells in raw[1:]:
        rec = {}
        for col, value in cells.items():
            field = COLUMN_MAP.get(header.get(col, ""))
            if field:
                rec[field] = (value or "").strip()
        if rec.get("code_raw") and rec.get("text"):
            out.append(rec)
    return out


def normalize_code(code_raw: str) -> str:
    """'[6사05-02]' → '6사05-02'"""
    return code_raw.strip().strip("[]").strip()


def seed(xlsx: Path, db: Path) -> int:
    rows = read_rows(xlsx)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.executescript(DDL)
        # 멱등: 매번 비우고 다시 채운다. 원본이 유일한 진실이다.
        conn.execute("DELETE FROM standards")
        conn.executemany(
            """INSERT INTO standards
               (code, code_raw, curriculum, school_level, grade_band, subject,
                area_code, text, ncic_id, basis, source_url, imported_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    normalize_code(r["code_raw"]), r["code_raw"],
                    r.get("curriculum"), r.get("school_level"), r.get("grade_band"),
                    r.get("subject"), r.get("area_code"), r["text"],
                    r.get("ncic_id"), r.get("basis"), r.get("source_url"), now,
                )
                for r in rows
            ],
        )
        conn.commit()

        total = conn.execute("SELECT count(*) FROM standards").fetchone()[0]
        print(f"✅ {total}개 성취기준 적재 → {db}")
        print("\n과목별 (5~6학년):")
        for subject, n in conn.execute(
            "SELECT subject, count(*) FROM standards "
            "WHERE grade_band LIKE '5%' GROUP BY subject ORDER BY subject"
        ):
            print(f"  {subject:<6} {n:>3}")
    finally:
        conn.close()
    return total


def check(db: Path, code: str) -> int:
    """CLAUDE.md B-1 이 실제로 작동하는지 확인하는 수동 조회."""
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT code, subject, grade_band, text, source_url FROM standards WHERE code = ?",
            (normalize_code(code),),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        print(f"❌ {code} — DB에 없음. 작업을 실패시켜야 한다.")
        return 1
    print(f"✅ {row[0]}  ({row[1]} {row[2]})\n   {row[3]}\n   출처: {row[4]}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--check", metavar="CODE", help="적재하지 않고 코드 하나만 조회")
    args = p.parse_args()

    if args.check:
        if not args.db.exists():
            print(f"❌ DB 없음: {args.db} — 먼저 시드하세요", file=sys.stderr)
            return 1
        return check(args.db, args.check)

    if not args.xlsx.exists():
        print(f"❌ 원본 없음: {args.xlsx}", file=sys.stderr)
        return 1
    seed(args.xlsx, args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
