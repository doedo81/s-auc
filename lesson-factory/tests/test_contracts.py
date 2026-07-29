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
TRACE = "사회-5-2-2단원-9차시"


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
    Draft202012Validator.check_schema(load(CONTRACTS / f"{name}.schema.json"))


# ------------------------------------------------------------ 정상 픽스처 통과

ALL_TRACES = ["실과-5-2-5단원-4차시", "사회-5-2-2단원-9차시"]


@pytest.mark.parametrize("trace", ALL_TRACES)
@pytest.mark.parametrize("kind,schema", [("plan", "lesson_plan"), ("worksheet", "worksheet"), ("deck", "slide_deck")])
def test_fixture_validates(trace: str, kind: str, schema: str) -> None:
    validator(schema).validate(load(FIXTURES / f"{trace}.{kind}.json"))


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
    bad = copy.deepcopy(plan)
    bad["activities"][1]["kagan_structure"] = None
    _rejects("lesson_plan", bad)


def test_rejects_unknown_kagan(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["activities"][1]["kagan_structure"] = "모둠 토의"
    _rejects("lesson_plan", bad)


def test_rejects_대체_without_rationale(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["activities"][1]["rationale"] = None
    _rejects("lesson_plan", bad)


def test_rejects_대체_without_replaces(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["activities"][1]["replaces"] = None
    _rejects("lesson_plan", bad)


def test_rejects_missing_social_skill(plan: dict) -> None:
    """사회적 기술은 약안·세안 모두의 필수 항목이다."""
    bad = copy.deepcopy(plan)
    del bad["social_skill"]
    _rejects("lesson_plan", bad)


def test_rejects_worksheet_items_without_활동지(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["activities"][0]["worksheet_items"] = ["SOMETHING"]
    _rejects("lesson_plan", bad)


def test_rejects_활동지_without_items(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["activities"][1]["worksheet_items"] = []
    _rejects("lesson_plan", bad)


def test_rejects_numbered_worksheet_id(plan: dict, worksheet: dict) -> None:
    """실물 활동지는 번호가 아니라 이름표를 쓴다 (W1 → PERSONAL_NOTE)."""
    bad_plan = copy.deepcopy(plan)
    bad_plan["activities"][1]["worksheet_items"] = ["W1", "W2"]
    _rejects("lesson_plan", bad_plan)

    bad_ws = copy.deepcopy(worksheet)
    bad_ws["items"][0]["id"] = "W1"
    _rejects("worksheet", bad_ws)


def test_rejects_malformed_standard_code(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["standards"] = ["[6사05-02]"]  # 대괄호는 벗겨서 저장한다
    _rejects("lesson_plan", bad)


def test_rejects_missing_copyright(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["copyright_notice"] = "자유롭게 쓰세요"
    _rejects("lesson_plan", bad)


def test_rejects_활동슬라이드_without_covers_activity(deck: dict) -> None:
    bad = copy.deepcopy(deck)
    for s in bad["slides"]:
        if s.get("role") == "활동":
            s["covers_activity"] = None
            break
    _rejects("slide_deck", bad)


def test_rejects_정답슬라이드_without_answer_of(deck: dict) -> None:
    bad = copy.deepcopy(deck)
    for s in bad["slides"]:
        if s.get("role") == "정답":
            s["answer_of"] = None
            break
    _rejects("slide_deck", bad)


def test_rejects_OX_with_wrong_count(deck: dict) -> None:
    bad = copy.deepcopy(deck)
    for s in bad["slides"]:
        if s.get("role") == "OX":
            s["ox_items"] = s["ox_items"][:3]
            break
    _rejects("slide_deck", bad)


def test_rejects_OX_without_rationale(deck: dict) -> None:
    """OX 는 정답만으로 부족하다 — 왜 그런지가 있어야 정정 지도가 된다."""
    bad = copy.deepcopy(deck)
    for s in bad["slides"]:
        if s.get("role") == "OX":
            del s["ox_items"][0]["rationale"]
            break
    _rejects("slide_deck", bad)


def test_accepts_open_slide_kind(deck: dict) -> None:
    """kind 는 개방형 — 차시별 서사를 막지 않는다 (실물이 고정 순서를 안 따른다)."""
    ok = copy.deepcopy(deck)
    ok["slides"][4]["kind"] = "설계 브리핑"
    validator("slide_deck").validate(ok)


def test_rejects_unknown_worksheet_role(worksheet: dict) -> None:
    bad = copy.deepcopy(worksheet)
    bad["items"][0]["role"] = "자유기록"
    _rejects("worksheet", bad)


def test_rejects_verdict_fail_without_fix() -> None:
    doc = {
        "trace_id": TRACE,
        "attempt": 1,
        "checks": [
            {"id": f"R{i}", "pass": True, "evidence": "산출물에서 해당 대목을 확인함"}
            for i in range(1, 9)
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
    bad = {
        "trace_id": TRACE,
        "attempt": 1,
        "checks": [{"id": "R1", "pass": True, "evidence": "산출물에서 확인함"}],
        "verdict": "PASS",
    }
    _rejects("verdict", bad)


# --------------------------------------------- 계약 파일들끼리 어긋나지 않는가

def test_kagan_enum_matches_structures_file() -> None:
    """스키마 enum 과 kagan_structures.json 이 어긋나면
    지도안은 통과하는데 구조 명세가 없는 사태가 난다."""
    kagan = load(CONTRACTS / "kagan_structures.json")
    ids = {s["id"] for s in kagan["structures"]}

    schema = load(CONTRACTS / "lesson_plan.schema.json")
    enum = schema["$defs"]["activity"]["properties"]["kagan_structure"]["enum"]
    enum_ids = {v for v in enum if v is not None}

    assert enum_ids == ids, f"불일치: 스키마에만 {enum_ids - ids}, 파일에만 {ids - enum_ids}"


def test_nine_structures_have_templates() -> None:
    """학습지 템플릿이 있는 구조는 9종. 이 9종만 역할 검증이 가능하다."""
    kagan = load(CONTRACTS / "kagan_structures.json")
    templated = [s for s in kagan["structures"] if s["has_template"]]
    assert len(templated) == 9, [s["id"] for s in templated]
    for s in templated:
        assert s["required_item_roles"], f"{s['id']}: 템플릿이 있는데 요구 역할이 비었다"
        assert s["template"], f"{s['id']}: 템플릿 경로가 없다"


def test_templateless_structures_skip_role_check() -> None:
    """템플릿 없는 구조는 활동지가 자유 형식이므로 요구 역할을 두지 않는다."""
    kagan = load(CONTRACTS / "kagan_structures.json")
    for s in kagan["structures"]:
        if not s["has_template"]:
            assert s["required_item_roles"] == [], f"{s['id']}: 템플릿 없이 역할을 요구하면 검증이 불가능하다"


def test_kagan_aliases_are_unambiguous() -> None:
    """별칭이 다른 구조의 이름과 겹치면 어느 구조를 뜻하는지 알 수 없게 된다.

    별칭은 실물 문서(분석표는 '모둠 합의', 템플릿은 '모두미 협의')의 표기 차이를
    흡수하려고 둔 것이다. 스키마 enum 은 정식 id 만 받는다.
    """
    kagan = load(CONTRACTS / "kagan_structures.json")
    ids_ = {s["id"] for s in kagan["structures"]}

    seen: dict[str, str] = {}
    for s in kagan["structures"]:
        for alias in s.get("aliases", []):
            assert alias not in ids_, f"'{alias}' 는 이미 정식 구조 이름이다"
            assert alias not in seen, f"'{alias}' 가 {seen[alias]} 와 {s['id']} 양쪽의 별칭이다"
            seen[alias] = s["id"]


def test_kagan_required_roles_exist() -> None:
    kagan = load(CONTRACTS / "kagan_structures.json")
    declared = set(kagan["item_roles"])

    ws_schema = load(CONTRACTS / "worksheet.schema.json")
    ws_roles = set(ws_schema["properties"]["items"]["items"]["properties"]["role"]["enum"])
    assert declared == ws_roles, f"불일치: {declared ^ ws_roles}"

    for s in kagan["structures"]:
        missing = set(s["required_item_roles"]) - declared
        assert not missing, f"{s['id']} 가 정의되지 않은 역할을 요구함: {missing}"


def test_rubric_headings_match_verdict_enum() -> None:
    """루브릭에 항목을 추가하고 verdict 스키마를 안 고치면, 검수자가 8개를 판정해도
    7개만 받는 사태가 난다. 반대면 검수자가 무엇을 판정해야 할지 모르는 칸이 생긴다."""
    import re

    rubric = (CONTRACTS / "rubric.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## (R[0-9]+) — ", rubric, flags=re.MULTILINE)

    schema = load(CONTRACTS / "verdict.schema.json")
    items = schema["properties"]["checks"]
    enum = items["items"]["properties"]["id"]["enum"]

    assert headings == enum, f"루브릭 {headings} ≠ 스키마 {enum}"
    assert items["minItems"] == items["maxItems"] == len(enum)


def test_era_enum_matches_palettes() -> None:
    palettes = set(load(CONTRACTS / "era_palettes.json")["eras"])
    plan_eras = set(load(CONTRACTS / "lesson_plan.schema.json")["properties"]["era"]["enum"])
    deck_eras = set(load(CONTRACTS / "slide_deck.schema.json")["properties"]["era"]["enum"])
    assert plan_eras == deck_eras == palettes


def test_all_palettes_confirmed() -> None:
    """2026-07-28 담임 확정. 색값이 비어 있으면 팔레트 검사가 무의미해진다."""
    for era, p in load(CONTRACTS / "era_palettes.json")["eras"].items():
        assert p["confirmed"], f"{era}: 미확정 팔레트가 남아 있다"
        if era == "해당없음":
            continue
        assert p["background"], f"{era}: background 가 비었다"
        assert p["accent"], f"{era}: accent 가 비었다"
        assert p["palette_name"], f"{era}: palette_name 이 비었다"
