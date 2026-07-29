"""기계 검증 — LLM 호출 없음.

CLAUDE.md C-1: 기계로 검사 가능한 것은 LLM에게 묻지 않는다.
여기서 실패하면 LLM 검수를 아예 호출하지 않는다 (비용 절감 + 원인 명확).

모든 검사는 순수 함수이며 `list[Problem]` 을 돌려준다. 빈 리스트 = 통과.
"""

from __future__ import annotations

from dataclasses import dataclass


#: 심각도 3단계.
#:
#:   error   실패. 여기서 멈추고 LLM 검수를 호출하지 않는다.
#:   review  실패는 아니지만 **사람이 봐야 한다.** 자동 배부·자동 승인으로 넘어가지 않는다.
#:   warn    기록만 남긴다.
#:
#: `review` 는 담임 요구에서 나왔다 — "더 많으면 나한테 좀 보여줘. 그래야 수정 좀 하고
#: 나눠주게." 기계가 임의로 자르면 학습에 필요한 칸이 날아가므로, 막지 않고 보여 준다.
SEVERITIES = ("error", "review", "warn")
_MARKS = {"error": "❌", "review": "🖐", "warn": "⚠️"}


@dataclass(frozen=True)
class Problem:
    check: str
    message: str
    severity: str = "error"

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"모르는 심각도: {self.severity!r} (가능한 값: {SEVERITIES})")

    def __str__(self) -> str:
        return f"{_MARKS[self.severity]} [{self.check}] {self.message}"


def has_errors(problems: list[Problem]) -> bool:
    return any(p.severity == "error" for p in problems)


def needs_review(problems: list[Problem]) -> bool:
    """사람이 봐야 하는 것이 있는가. 자동 진행 여부를 여기서 가른다."""
    return any(p.severity == "review" for p in problems)
