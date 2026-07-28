"""P0 계약 검증.

이 테스트는 LLM을 호출하지 않는다. 계약 파일들끼리 서로 어긋나지 않는지,
그리고 스키마가 실제로 불량 데이터를 걸러내는지 확인한다.

CLAUDE.md E: "통과 픽스처와 실패 픽스처를 함께 테스트한다 — 통과만 하는 검사는 검사가 아니다."
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

CONTRACTS = Path(__file__).resolve().parent.parent / "contracts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TRACE = "사회-5-2-2단원-1차시"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load(CONTRACTS / f"{name}.schema.json"))


@pytest.fixture(scope="module")
def plan() -> dict:
    return load(FIXTURES / f"{TRACE}.plan.json")


@pytest.fixture(scope="module")
def worksheet() -> dict:
    return load(FIXTURES / f"{TRACE}.worksheet.json")


@pytest.fixture(scope="module")
def deck() -> dict:
    return load(FIXTURES / f"{TRACE}.deck.json")


# ---------------------------------------------------------------- 스키마 자체

@pytest.mark.parametrize("name", ["lesson_plan", "worksheet", "slide_deck", "verdict"])
def test_schema_is_wellformed(name: str) -> None:
    """스키마 파일 자체가 유효한 JSON Schema 인가."""
    Draft202012Validator.check_schema(load(CONTRACTS / f"{name}.schema.json"))


# ------------------------------------------------------------ 정상 픽스처 통과

def test_valid_plan_passes(plan: dict) -> None:
    validator("lesson_plan").validate(plan)


def test_valid_worksheet_passes(worksheet: dict) -> None:
    validator("worksheet").validate(worksheet)


def test_valid_deck_passes(deck: dict) -> None:
    validator("slide_deck").validate(deck)


# -------------------------------------------------- 불량 픽스처가 실제로 걸리는가

def _rejects(name: str, doc: dict) -> None:
    errors = list(validator(name).iter_errors(doc))
    assert errors, "스키마가 불량 데이터를 통과시켰다"


def test_rejects_활동_without_objective(plan: dict) -> None:
    """모든 활동은 최소 1개 학습목표에 연결되어야 한다 (교과서 대체 정책의 방어선)."""
    bad = copy.deepcopy(plan)
    bad["activities"][1]["objective_ids"] = []
    _rejects("lesson_plan", bad)


def test_rejects_전개_without_kagan(plan: dict) -> None:
    """전개 활동은 케이건 구조 9종 중 하나를 반드시 쓴다."""
    bad = copy.deepcopy(plan)
    bad["activities"][1]["kagan_structure"] = None
    _rejects("lesson_plan", bad)


def test_rejects_unknown_kagan(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["activities"][1]["kagan_structure"] = "모둠 토의"
    _rejects("lesson_plan", bad)


def test_rejects_대체_without_rationale(plan: dict) -> None:
    """교과서를 벗어났으면 무엇을 왜 바꿨는지 반드시 남긴다."""
    bad = copy.deepcopy(plan)
    bad["activities"][1]["rationale"] = None
    _rejects("lesson_plan", bad)


def test_rejects_대체_without_replaces(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["activities"][1]["replaces"] = None
    _rejects("lesson_plan", bad)


def test_rejects_worksheet_items_without_활동지(plan: dict) -> None:
    """활동지를 쓰지 않는데 항목을 참조하면 어딘가 어긋난 것이다."""
    bad = copy.deepcopy(plan)
    bad["activities"][0]["worksheet_items"] = ["W9"]
    _rejects("lesson_plan", bad)


def test_rejects_활동지_without_items(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["activities"][1]["worksheet_items"] = []
    _rejects("lesson_plan", bad)


def test_rejects_malformed_standard_code(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["standards"] = ["[6사03-02]"]  # 대괄호는 저장하지 않는다
    _rejects("lesson_plan", bad)


def test_rejects_missing_copyright(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["copyright_notice"] = "자유롭게 쓰세요"
    _rejects("lesson_plan", bad)


def test_rejects_활동슬라이드_without_covers_activity(deck: dict) -> None:
    bad = copy.deepcopy(deck)
    for s in bad["slides"]:
        if s["kind"] == "활동":
            s["covers_activity"] = None
            break
    _rejects("slide_deck", bad)


def test_rejects_정답슬라이드_without_answer_of(deck: dict) -> None:
    """정답은 반드시 어느 문제의 정답인지 밝힌다 (문제·정답 분리 규칙)."""
    bad = copy.deepcopy(deck)
    for s in bad["slides"]:
        if s["kind"] == "정답":
            s["answer_of"] = None
            break
    _rejects("slide_deck", bad)


def test_rejects_OX_with_wrong_count(deck: dict) -> None:
    bad = copy.deepcopy(deck)
    for s in bad["slides"]:
        if s["kind"] == "OX":
            s["ox_items"] = s["ox_items"][:3]
            break
    _rejects("slide_deck", bad)


def test_rejects_unknown_worksheet_role(worksheet: dict) -> None:
    bad = copy.deepcopy(worksheet)
    bad["items"][0]["role"] = "자유기록"
    _rejects("worksheet", bad)


def test_rejects_verdict_fail_without_fix() -> None:
    """불합격 판정에는 반드시 수정안과 대상이 따라야 한다."""
    doc = {
        "trace_id": TRACE,
        "attempt": 1,
        "checks": [
            {"id": f"R{i}", "pass": True, "evidence": "산출물에서 해당 대목을 확인함"} for i in range(1, 8)
        ],
        "verdict": "PASS",
    }
    validator("verdict").validate(doc)  # 정상 케이스

    bad = copy.deepcopy(doc)
    bad["checks"][3] = {"id": "R4", "pass": False, "evidence": "'신분제의 동요'"}
    bad["verdict"] = "REVISE"
    bad["assigned_to"] = "teacher"
    _rejects("verdict", bad)


def test_rejects_verdict_with_partial_checks() -> None:
    """R1~R7 을 전부 채워야 한다 — 일부만 보고 판정하지 않는다."""
    bad = {
        "trace_id": TRACE,
        "attempt": 1,
        "checks": [{"id": "R1", "pass": True, "evidence": "산출물에서 해당 대목을 확인함"}],
        "verdict": "PASS",
    }
    _rejects("verdict", bad)


# --------------------------------------------- 계약 파일들끼리 어긋나지 않는가

def test_kagan_enum_matches_structures_file() -> None:
    """lesson_plan 스키마의 케이건 enum 과 kagan_structures.json 이 어긋나면
    지도안은 통과하는데 활동지 템플릿이 없는 사태가 난다."""
    kagan = load(CONTRACTS / "kagan_structures.json")
    ids = {s["id"] for s in kagan["structures"]}

    schema = load(CONTRACTS / "lesson_plan.schema.json")
    enum = schema["$defs"]["activity"]["properties"]["kagan_structure"]["enum"]
    enum_ids = {v for v in enum if v is not None}

    assert enum_ids == ids, f"불일치: 스키마에만 {enum_ids - ids}, 파일에만 {ids - enum_ids}"
    assert len(ids) == 9, "학습지 템플릿이 있는 구조는 9종이다"


def test_kagan_required_roles_exist() -> None:
    """구조가 요구하는 항목 역할이 worksheet 스키마의 role enum 에 전부 있는가."""
    kagan = load(CONTRACTS / "kagan_structures.json")
    declared = set(kagan["item_roles"])

    ws_schema = load(CONTRACTS / "worksheet.schema.json")
    ws_roles = set(ws_schema["properties"]["items"]["items"]["properties"]["role"]["enum"])
    assert declared == ws_roles, f"불일치: {declared ^ ws_roles}"

    for s in kagan["structures"]:
        missing = set(s["required_item_roles"]) - declared
        assert not missing, f"{s['id']} 가 정의되지 않은 역할을 요구함: {missing}"


def test_era_enum_matches_palettes() -> None:
    palettes = set(load(CONTRACTS / "era_palettes.json")["eras"])
    plan_eras = set(load(CONTRACTS / "lesson_plan.schema.json")["properties"]["era"]["enum"])
    deck_eras = set(load(CONTRACTS / "slide_deck.schema.json")["properties"]["era"]["enum"])
    assert plan_eras == deck_eras == palettes


def test_confirmed_palette_has_hex() -> None:
    """confirmed=true 인데 색값이 비어 있으면 검사가 무의미해진다."""
    for era, p in load(CONTRACTS / "era_palettes.json")["eras"].items():
        if p["confirmed"] and era != "해당없음":
            assert p["background"], f"{era}: confirmed 인데 background 가 비었다"
            assert p["primary"], f"{era}: confirmed 인데 primary 가 비었다"


def test_fixture_deck_palette_matches_era(deck: dict) -> None:
    palettes = load(CONTRACTS / "era_palettes.json")["eras"]
    expected = palettes[deck["era"]]
    if expected["confirmed"] and deck["era"] != "해당없음":
        assert deck["palette"]["background"] == expected["background"]
        assert deck["palette"]["primary"] == expected["primary"]
