"""기계 검증 — LLM 호출 없음.

CLAUDE.md C-1: 기계로 검사 가능한 것은 LLM에게 묻지 않는다.
여기서 실패하면 LLM 검수를 아예 호출하지 않는다 (비용 절감 + 원인 명확).

모든 검사는 순수 함수이며 `list[Problem]` 을 돌려준다. 빈 리스트 = 통과.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Problem:
    check: str
    message: str
    severity: str = "error"  # "error" | "warn"

    def __str__(self) -> str:
        mark = "❌" if self.severity == "error" else "⚠️"
        return f"{mark} [{self.check}] {self.message}"


def has_errors(problems: list[Problem]) -> bool:
    return any(p.severity == "error" for p in problems)
