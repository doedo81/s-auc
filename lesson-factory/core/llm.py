"""LLM 어댑터. **JSON 입력 → JSON 출력, 한 번.** (CLAUDE.md C-3)

이 파일이 하는 일은 넷뿐이다.

1. 프롬프트(md)와 입력(dict)을 한 번의 호출로 보낸다
2. 돌아온 텍스트에서 JSON 을 꺼낸다
3. 토큰·비용을 `llm_calls` 에 적는다 (B-4)
4. 작업당 비용 상한을 넘으면 멈춘다

**모델이 다른 모델을 부르지 않는다.** 도구도 주지 않는다 — 교사 에이전트는 글을 쓰는
일만 하고, 파일을 읽고 쓰는 것은 코드가 한다.

오프라인 모드가 따로 있는 이유: `checks/` 와 렌더러 시험을 API 없이 돌려야 하기
때문이다. 테스트가 돈을 쓰기 시작하면 아무도 테스트를 돌리지 않는다.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import db
from .config import Config

# 세안 하나가 6천 토큰쯤 된다. 넉넉히 두되 스트리밍 경계(~16000) 안에 둔다.
MAX_TOKENS = 16000
TIMEOUT_SECONDS = 600.0
MAX_RETRIES = 3


class LLMError(RuntimeError):
    pass


class CostLimitExceeded(LLMError):
    pass


@dataclass
class Reply:
    data: dict
    in_tokens: int
    out_tokens: int
    cost_usd: float | None
    stop_reason: str | None


def extract_json(text: str) -> dict:
    """모델 답에서 JSON 객체를 꺼낸다.

    프롬프트가 '코드펜스를 붙이지 마라' 라고 해 두었지만 붙어서 올 때가 있다.
    그것 하나 때문에 작업을 실패시키는 것은 아깝다 — 벗겨 내고 계속한다.
    다만 **내용을 고치지는 않는다.** 파싱이 안 되면 실패다.
    """
    stripped = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1).strip()
    if not stripped.startswith("{"):
        start, end = stripped.find("{"), stripped.rfind("}")
        if start == -1 or end <= start:
            raise LLMError(f"JSON 을 찾지 못했다: {text[:200]!r}")
        stripped = stripped[start : end + 1]
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LLMError(f"JSON 파싱 실패: {exc}") from exc


class Client:
    """Anthropic 호출 한 겹. 오프라인이면 녹음본을 돌려준다."""

    def __init__(self, config: Config, conn: sqlite3.Connection, *, offline_dir: Path | None = None):
        self.config = config
        self.conn = conn
        self.offline_dir = offline_dir
        self._sdk = None

    # ---------------------------------------------------------------- 오프라인

    def _replay(self, agent: str, trace_id: str) -> Reply:
        path = self.offline_dir / f"{trace_id}.{agent}.json"
        if not path.exists():
            raise LLMError(
                f"오프라인 모드인데 녹음본이 없다: {path}\n"
                "실제 호출을 하려면 --offline 을 빼고 .env 에 ANTHROPIC_API_KEY 를 넣는다."
            )
        return Reply(json.loads(path.read_text(encoding="utf-8")), 0, 0, 0.0, "offline")

    # ---------------------------------------------------------------- 실제 호출

    def _client(self):
        if self._sdk is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - 설치 안내
                raise LLMError("anthropic 패키지가 없다. pip install -r requirements.txt") from exc
            if not self.config.api_key:
                raise LLMError("ANTHROPIC_API_KEY 가 없다. .env 를 채우거나 --offline 로 돌린다.")
            self._sdk = anthropic.Anthropic(
                api_key=self.config.api_key,
                timeout=TIMEOUT_SECONDS,
                max_retries=MAX_RETRIES,  # 429·5xx·연결 오류는 SDK 가 지수 백오프로 재시도한다
            )
        return self._sdk

    def call_json(self, *, agent: str, trace_id: str, prompt: str, payload: dict) -> Reply:
        """프롬프트 + 입력 JSON → 출력 JSON. 호출은 한 번뿐이다."""
        self._guard_budget(trace_id)

        if self.offline_dir is not None:
            return self._replay(agent, trace_id)

        message = self._client().messages.create(
            model=self.config.model,
            max_tokens=MAX_TOKENS,
            system=prompt,
            output_config={"effort": self.config.effort},
            messages=[{
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, indent=2),
            }],
        )

        # 안전 분류기가 거절하면 content 가 비어 있다. 먼저 본다.
        if message.stop_reason == "refusal":
            self._record(agent, trace_id, message, None)
            raise LLMError(f"모델이 요청을 거절했다 (stop_reason=refusal). trace={trace_id}")

        text = "".join(b.text for b in message.content if b.type == "text")
        if message.stop_reason == "max_tokens":
            raise LLMError(f"{MAX_TOKENS} 토큰에서 잘렸다. 세안이 끝까지 나오지 않았다. trace={trace_id}")

        data = extract_json(text)
        cost = self._record(agent, trace_id, message, None)
        usage = message.usage
        return Reply(data, usage.input_tokens, usage.output_tokens, cost, message.stop_reason)

    # ------------------------------------------------------------------ 기록

    def _record(self, agent: str, trace_id: str, message, _unused) -> float | None:
        usage = message.usage
        cost = db.cost_usd(self.config.model, usage.input_tokens, usage.output_tokens)
        db.record_llm_call(
            self.conn,
            trace_id=trace_id,
            agent=agent,
            model=self.config.model,
            effort=self.config.effort,
            in_tokens=usage.input_tokens,
            out_tokens=usage.output_tokens,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cost_usd=cost,
            stop_reason=message.stop_reason,
        )
        return cost

    def _guard_budget(self, trace_id: str) -> None:
        limit = self.config.cost_limit_usd
        if limit is None:
            return  # 환율을 모르면 상한도 없다 — run.py 가 이 사실을 사람에게 알린다
        spent = db.spent_usd(self.conn, trace_id)
        if spent >= limit:
            raise CostLimitExceeded(
                f"작업 비용 상한 초과: ${spent:.4f} / ${limit:.4f} (trace={trace_id})"
            )


class ClaudeCodeClient(Client):
    """구독제로 돌리는 길 — Claude Code CLI 를 헤드리스(`claude -p`)로 부른다.

    담임 질문(2026-07-29): *"난 정액제인데 API 키를 꼭 써야 돼?"* 아니다.
    구독은 Claude Code 사용을 덮고, Claude Code 에는 비대화형 모드가 있다.
    API 키는 **종량제 별도 청구**라서 구독과 지갑이 다르다.

    보내는 모양은 API 쪽과 같다 — 시스템 자리에 프롬프트, 사용자 자리에 입력 JSON.
    그래야 나중에 API 로 옮겨도 결과가 달라지지 않는다.

    두 가지는 API 경로와 다르고, 다르다는 것을 알고 써야 한다.

    1. **군더더기 토큰이 붙는다.** Claude Code 자체 시스템 프롬프트가 매 호출에
       2만 7천 토큰쯤 실린다(실측). 구독제에서는 돈이 아니라 사용량으로 나간다.
    2. **`total_cost_usd` 는 청구액이 아니라 환산액이다.** 구독제면 실제로 빠져나가는
       돈이 아니므로, 이 값으로 상한을 걸면 있지도 않은 돈을 세게 된다.
    """

    CLI_TIMEOUT = 900  # effort high 로 세안 한 편이면 몇 분씩 걸린다

    def __init__(self, config: Config, conn: sqlite3.Connection, *, binary: str = "claude"):
        super().__init__(config, conn, offline_dir=None)
        self.binary = binary

    @staticmethod
    def available(binary: str = "claude") -> bool:
        return shutil.which(binary) is not None

    def call_json(self, *, agent: str, trace_id: str, prompt: str, payload: dict) -> Reply:
        self._guard_budget(trace_id)

        if not self.available(self.binary):
            raise LLMError(f"{self.binary} 를 찾지 못했다. Claude Code 가 설치돼 있어야 한다.")

        argv = [
            self.binary, "-p", "--output-format", "json",
            "--model", self.config.model,
            "--effort", self.config.effort,
            "--append-system-prompt", prompt,
            # ★ 도구를 전부 끈다. 이게 없으면 CLI 가 에이전트 루프로 돌아
            #   파일을 읽고 여러 턴을 돌린다 — CLAUDE.md C-3("에이전트는 LLM 호출
            #   1회다")을 어기는 것이고, 실측으로 출력 4만·캐시 12만 토큰이 나왔다.
            #   교사 에이전트는 글을 쓰는 일만 하고, 자료를 읽는 것은 코드가 한다.
            "--tools", "",
            "--strict-mcp-config",   # 세션에 붙은 MCP 서버도 들어오지 않게
        ]
        try:
            proc = subprocess.run(
                argv,
                input=json.dumps(payload, ensure_ascii=False, indent=2),
                capture_output=True, text=True, timeout=self.CLI_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"{self.CLI_TIMEOUT}초 안에 끝나지 않았다 (trace={trace_id})") from exc

        if proc.returncode != 0:
            raise LLMError(f"claude -p 실패 (exit {proc.returncode}): {proc.stderr.strip()[:400]}")

        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise LLMError(f"claude -p 출력이 JSON 이 아니다: {proc.stdout[:300]!r}") from exc

        if envelope.get("is_error"):
            raise LLMError(f"claude -p 오류: {envelope.get('result', '')[:400]}")

        usage = envelope.get("usage", {})
        in_tokens = int(usage.get("input_tokens", 0))
        out_tokens = int(usage.get("output_tokens", 0))
        # CLI 가 계산해 준 값을 그대로 쓴다. 우리 단가표로 다시 계산하면 캐시 토큰을
        # 빼먹어서 실제와 어긋난다 — 어긋난 숫자를 기록하느니 CLI 것을 믿는다.
        cost = envelope.get("total_cost_usd")

        db.record_llm_call(
            self.conn,
            trace_id=trace_id, agent=agent, model=self.config.model, effort=self.config.effort,
            in_tokens=in_tokens, out_tokens=out_tokens,
            cache_write_tokens=int(usage.get("cache_creation_input_tokens", 0)),
            cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
            cost_usd=cost, stop_reason=envelope.get("stop_reason"),
        )

        return Reply(extract_json(envelope.get("result", "")), in_tokens, out_tokens, cost,
                     envelope.get("stop_reason"))
