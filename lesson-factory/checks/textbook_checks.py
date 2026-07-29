"""교과서 대조 — 지도안이 교과서와 같은 곳을 가리키는가.

담임 요구(2026-07-29): **"교과서 학습목표 일치시키고. 지금은 사회 교과서만 있는데
계속 보충해줄게."**

지금까지 학습목표의 출처는 약안·세안이었다. 둘 다 선생님이 쓰신 것이라 교과서가
인쇄한 목표와 어긋날 수 있고, 어긋나도 알 방법이 없었다. 성취기준을 NCIC DB 로
고정한 것과 같은 이유로 교과서 목표도 고정한다.

## 세 단계로 나눈 이유

    미등록          경고. 아직 등록 안 된 과목·차시다. **작업을 막지 않는다**
    등록 · 미대조    경고. 선생님 자료에서 옮겨 적은 값이라 교과서 원본이 아니다
    등록 · 대조완료  실패. 교과서를 펴서 확인한 값과 어긋나면 지도안이 틀린 것이다

성취기준에서 이미 겪은 일이다 — 학기계획표에 "웹 확인, 총론 대조 예정" 이라고 적혀
있던 5개가 나중에 NCIC 원본과 전부 일치했다. 대조 전과 후를 구분해 두지 않으면
그 확인이 있었는지 알 수 없게 된다.

**미등록을 실패로 만들지 않는 이유**: 사회 말고는 아직 교과서가 없다. 없는 것을
실패로 만들면 다른 과목을 시작할 수 없고, 그러면 등록부를 지어내서 채우게 된다.
그건 CLAUDE.md B-1(성취기준 지어내기 금지)이 막으려던 바로 그 일이다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import Problem

REGISTRY = Path(__file__).resolve().parent.parent / "curriculum" / "textbook"


def _normalize(s: str) -> str:
    """구두점·공백 차이는 불일치가 아니다. cross_checks 와 같은 기준을 쓴다."""
    return re.sub(r"[\s.,·]", "", s)


def load_registry(subject: str, grade: int, semester: int, root: Path | None = None) -> dict | None:
    """과목별 등록부. 없으면 None — 없는 것과 비어 있는 것을 구분한다."""
    path = (root or REGISTRY) / f"{subject}-{grade}-{semester}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def find_lesson(registry: dict, period: str) -> dict | None:
    for unit in registry["units"]:
        for lesson in unit["lessons"]:
            if lesson["period"] == period:
                return lesson
    return None


def check_textbook_objective(plan: dict, root: Path | None = None) -> list[Problem]:
    """지도안 학습목표가 교과서 차시 목표와 맞는가."""
    meta = plan["meta"]
    registry = load_registry(meta["subject"], meta["grade"], meta["semester"], root)

    if registry is None:
        return [
            Problem(
                "textbook",
                f"{meta['subject']} {meta['grade']}-{meta['semester']} 교과서가 등록되지 않음 — "
                f"curriculum/textbook/ 에 넣으면 학습목표를 대조한다",
                severity="warn",
            )
        ]

    lesson = find_lesson(registry, meta["period"])
    if lesson is None:
        return [
            Problem("textbook", f"교과서 등록부에 {meta['period']} 차시가 없음", severity="warn")
        ]

    severity = "error" if lesson["verified"] else "warn"
    problems: list[Problem] = []

    want = _normalize(lesson["objective"])
    if not any(_normalize(o["text"]) == want for o in plan["objectives"]):
        got = " / ".join(o["text"] for o in plan["objectives"])
        tail = "" if lesson["verified"] else " (아직 교과서 원본 대조 전이라 경고로 둔다)"
        problems.append(
            Problem(
                "textbook",
                f"학습목표가 교과서와 다름 — 교과서 “{lesson['objective']}” / 지도안 “{got}”{tail}",
                severity=severity,
            )
        )

    if lesson.get("pages") and meta.get("textbook_pages") and lesson["pages"] != meta["textbook_pages"]:
        problems.append(
            Problem(
                "textbook",
                f"교과서 쪽이 다름 — 등록부 {lesson['pages']} / 지도안 {meta['textbook_pages']}",
                severity=severity,
            )
        )

    return problems


def check_textbook_standards(plan: dict, root: Path | None = None) -> list[Problem]:
    """이 차시가 속한 소단원의 성취기준을 지도안이 쓰고 있는가.

    성취기준 DB 는 '코드가 실재하는가' 까지만 본다. 같은 과목 안에서 엉뚱한 단원의
    코드를 붙인 것은 못 잡았는데(test_existing_but_wrong_standard_is_NOT_caught),
    교과서 등록부가 있으면 그 구멍이 메워진다.
    """
    meta = plan["meta"]
    registry = load_registry(meta["subject"], meta["grade"], meta["semester"], root)
    if registry is None:
        return []

    for unit in registry["units"]:
        if not any(le["period"] == meta["period"] for le in unit["lessons"]):
            continue
        expected = set(unit.get("standards") or [])
        if not expected:
            return []
        used = set(plan["standards"])
        if not (used & expected):
            return [
                Problem(
                    "textbook_standards",
                    f"{meta['period']} 차시는 '{unit.get('sub_unit') or unit['unit']}' 이고 "
                    f"성취기준이 {sorted(expected)} 인데 지도안은 {sorted(used)} 를 씀",
                )
            ]
        return []
    return []


def run_all(plan: dict, root: Path | None = None) -> list[Problem]:
    return check_textbook_objective(plan, root) + check_textbook_standards(plan, root)
