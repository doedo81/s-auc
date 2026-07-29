"""기계 검증 테스트 — LLM 호출 없음, 비용 0원.

각 검사마다 통과 케이스와 실패 케이스를 함께 둔다.
통과만 하는 검사는 검사가 아니다.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from checks import Problem, has_errors  # noqa: E402
from checks import cross_checks, plan_checks  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
DB = ROOT / "curriculum" / "standards.sqlite"
TRACE = "사회-5-2-2단원-9차시"

# 실물에서 옮긴 골든 픽스처와, 스키마 시연용으로 지어낸 예시 픽스처.
# 출처 구분은 tests/fixtures/README.md 참조.
ALL_TRACES = ["실과-5-2-5단원-4차시", "사회-5-2-2단원-9차시"]


def load(suffix: str, trace: str = TRACE) -> dict:
    return json.loads((FIXTURES / f"{trace}.{suffix}.json").read_text(encoding="utf-8"))


@pytest.fixture
def plan() -> dict:
    return load("plan")


@pytest.fixture
def worksheet() -> dict:
    return load("worksheet")


@pytest.fixture
def deck() -> dict:
    return load("deck")


def ids(problems: list[Problem]) -> set[str]:
    return {p.check for p in problems}


# ------------------------------------------------------------ 픽스처 전부 통과

@pytest.mark.parametrize("trace", ALL_TRACES)
def test_plan_checks_have_no_errors(trace: str) -> None:
    problems = plan_checks.run_all(load("plan", trace), DB if DB.exists() else None)
    assert not has_errors(problems), [str(p) for p in problems]


@pytest.mark.parametrize("trace", ALL_TRACES)
def test_unregistered_textbook_only_warns(trace: str) -> None:
    """이 두 픽스처는 교과서 등록부에 없다 — 실과는 과목째로, 사회 9차시는 차시가.

    경고까지만 내는 것이 설계다. 담임이 "지금은 사회 교과서만 있는데 계속 보충해줄게"
    라고 했으므로, 없는 것을 실패로 만들면 다른 과목을 시작할 수 없다.
    """
    problems = plan_checks.run_all(load("plan", trace), DB if DB.exists() else None)
    assert any(p.check == "textbook" for p in problems)
    assert not has_errors(problems)


@pytest.mark.parametrize("trace", ALL_TRACES)
def test_cross_checks_have_no_errors(trace: str) -> None:
    problems = cross_checks.run_all(
        load("plan", trace), load("worksheet", trace), load("deck", trace)
    )
    assert not has_errors(problems), [str(p) for p in problems]


@pytest.mark.parametrize("trace", ALL_TRACES)
def test_old_fixtures_warn_about_missing_skeleton(trace: str) -> None:
    """이 두 픽스처는 활동지 골격(학습 목표·교과서 쪽·힌트·마무리 루틴)이 없다.

    사회 5-2 제작 규칙 §3·§4 가 '매 차시' 요구하는 것들인데, 두 픽스처를 만들 때는
    실물 학습지 PDF 를 아직 찾지 못해 담지 못했다. 경고가 그 사실을 들고 있다 —
    조용히 통과시키면 '골격이 없어도 된다'가 되어 버린다.

    실물을 확보한 사회 1차시는 이 경고가 없다(tests/test_sean.py).
    """
    problems = cross_checks.check_worksheet_skeleton(
        load("plan", trace), load("worksheet", trace)
    )
    assert {p.check for p in problems} == {"worksheet_skeleton"}
    assert not has_errors(problems)


def test_실과_deck_has_all_answer_pairs() -> None:
    """실물 4차시는 문제→정답 쌍이 4개(3-4, 5-6, 16-17, 18-19)다."""
    deck = load("deck", "실과-5-2-5단원-4차시")
    pairs = [(s["answer_of"], s["index"]) for s in deck["slides"] if s.get("role") == "정답"]
    assert pairs == [(3, 4), (5, 6), (16, 17), (18, 19)]
    assert cross_checks.check_answer_separation(deck) == []


# ------------------------------------------------------------------ 지도안 검사

def test_minutes_sum_detected(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["activities"][0]["minutes"] = 4  # 40 → 39
    assert "minutes_sum" in ids(plan_checks.check_minutes_sum(bad))


def test_orphan_objective_detected(plan: dict) -> None:
    """아무 활동도 다루지 않는 학습목표 — 계획서에 있지만 수업에는 없는 목표."""
    bad = copy.deepcopy(plan)
    bad["objectives"].append({"id": "O2", "text": "실학자의 주장을 비교할 수 있다"})
    problems = plan_checks.check_objective_coverage(bad)
    assert "objective_coverage" in ids(problems)
    assert any("O2" in p.message for p in problems)


def test_dangling_objective_ref_detected(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["activities"][0]["objective_ids"] = ["O9"]
    assert "objective_coverage" in ids(plan_checks.check_objective_coverage(bad))


def test_monotonous_kagan_warns(plan: dict) -> None:
    """전개가 전부 같은 구조면 경고 — 실패는 아니지만 40분이 단조로워진다."""
    bad = copy.deepcopy(plan)
    bad["activities"][2]["kagan_structure"] = bad["activities"][1]["kagan_structure"]
    problems = plan_checks.check_kagan_usage(bad)
    assert problems and all(p.severity == "warn" for p in problems)
    assert not has_errors(problems)


def test_replacement_without_rationale_detected(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["activities"][1]["rationale"] = ""
    assert "replacement" in ids(plan_checks.check_replacement_justified(bad))


# ----------------------------------------------------------- 성취기준 DB (B-1)

@pytest.mark.skipif(not DB.exists(), reason="scripts/seed_standards.py 를 먼저 실행")
def test_real_standard_passes(plan: dict) -> None:
    assert plan_checks.check_standards_exist(plan, DB) == []


@pytest.mark.skipif(not DB.exists(), reason="scripts/seed_standards.py 를 먼저 실행")
def test_fabricated_standard_rejected(plan: dict) -> None:
    """모델이 지어낸 코드는 DB에 없으므로 작업이 실패한다."""
    bad = copy.deepcopy(plan)
    bad["standards"] = ["6사99-01"]
    assert "standards_exist" in ids(plan_checks.check_standards_exist(bad, DB))


@pytest.mark.skipif(not DB.exists(), reason="scripts/seed_standards.py 를 먼저 실행")
def test_wrong_subject_standard_rejected(plan: dict) -> None:
    """사회 수업에 실과 성취기준을 붙인 경우 — 코드는 실재하지만 과목이 다르다."""
    bad = copy.deepcopy(plan)
    bad["standards"] = ["6실04-01"]
    assert "standards_subject" in ids(plan_checks.check_standards_subject_match(bad, DB))


@pytest.mark.skipif(not DB.exists(), reason="scripts/seed_standards.py 를 먼저 실행")
def test_subject_alias_resolved() -> None:
    """NCIC 과목명 '실과(기술 · 가정)/정보' 와 교실 과목명 '실과' 를 같게 본다."""
    실과 = load("plan", "실과-5-2-5단원-4차시")
    assert plan_checks.check_standards_subject_match(실과, DB) == []


@pytest.mark.skipif(not DB.exists(), reason="scripts/seed_standards.py 를 먼저 실행")
def test_existing_but_wrong_standard_is_NOT_caught(plan: dict) -> None:
    """한계를 명시적으로 기록해 둔다.

    '6사03-02'(인권)는 실재하므로 DB 검사를 통과한다. 조선 후기 수업에
    전혀 맞지 않는데도 기계는 잡지 못한다. 의미 정합은 LLM 검수 R1/R7 의 몫이다.
    이 테스트가 실패하기 시작하면 기계 검사가 의미 검증까지 하게 된 것이므로
    루브릭에서 해당 항목을 덜어내도 되는지 검토한다.
    """
    wrong = copy.deepcopy(plan)
    wrong["standards"] = ["6사03-02"]
    assert plan_checks.check_standards_exist(wrong, DB) == []


# ------------------------------------------------------------------ 교차 검사

def test_missing_worksheet_item_detected(plan: dict, worksheet: dict) -> None:
    bad = copy.deepcopy(worksheet)
    bad["items"] = [i for i in bad["items"] if i["id"] != "PAIR_COMPARE"]
    assert "worksheet_refs" in ids(cross_checks.check_worksheet_item_refs(plan, bad))


def test_unused_worksheet_item_detected(plan: dict, worksheet: dict) -> None:
    """활동지에는 있는데 아무 활동도 안 쓰는 칸 — 학생이 빈칸을 만난다."""
    bad = copy.deepcopy(worksheet)
    bad["items"].append({
        "id": "EXTRA_BOX", "role": "모둠공유", "for_activity": "A3",
        "prompt": "쓰이지 않는 칸", "answer_space": "줄", "lines": 2,
    })
    assert "worksheet_refs" in ids(cross_checks.check_worksheet_item_refs(plan, bad))


def test_kagan_drift_detected(plan: dict, worksheet: dict) -> None:
    """★ 드리프트 검출 — 계획한 구조를 활동지가 지탱하지 않는 경우.

    실과 3차시에서 실제로 일어난 일: 계획은 '부채모양 뽑기'인데 산출물은 '직소'.
    여기서는 '생각-쓰기-짝-비교'를 골라 놓고 개인쓰기 칸을 없앤다 —
    비교할 산출물이 사라져 구조가 이름만 남는다.
    """
    bad = copy.deepcopy(worksheet)
    for item in bad["items"]:
        if item["id"] == "PERSONAL_NOTE":
            item["role"] = "모둠공유"  # 개인쓰기 → 모둠공유 로 바뀜
    problems = cross_checks.check_kagan_roles_satisfied(plan, bad)
    assert "kagan_roles" in ids(problems)
    assert any("개인쓰기" in p.message for p in problems)


def test_kagan_roles_satisfied_on_golden(plan: dict, worksheet: dict) -> None:
    assert cross_checks.check_kagan_roles_satisfied(plan, worksheet) == []


def test_templateless_structure_skipped(plan: dict, worksheet: dict) -> None:
    """템플릿 없는 구조는 활동지가 자유 형식이므로 역할 검사를 건너뛴다."""
    p = copy.deepcopy(plan)
    p["activities"][1]["kagan_structure"] = "브레인라이팅"
    assert cross_checks.check_kagan_roles_satisfied(p, worksheet) == []


def test_uncovered_activity_detected(plan: dict, deck: dict) -> None:
    bad = copy.deepcopy(deck)
    for s in bad["slides"]:
        if s.get("covers_activity") == "A3":
            s["covers_activity"] = None
    assert "slide_coverage" in ids(cross_checks.check_activity_slide_coverage(plan, bad))


def test_answer_leak_detected(deck: dict) -> None:
    """정답이 문제 슬라이드 본문에 미리 노출된 경우."""
    bad = copy.deepcopy(deck)
    q = next(s for s in bad["slides"] if s.get("role") == "문제")
    q["body"].append("공명첩")
    assert "answer_separation" in ids(cross_checks.check_answer_separation(bad))


def test_ox_answer_leak_detected(deck: dict) -> None:
    bad = copy.deepcopy(deck)
    ox = next(s for s in bad["slides"] if s.get("role") == "OX")
    ox["body"].append(ox["ox_items"][0]["rationale"])
    assert "answer_separation" in ids(cross_checks.check_answer_separation(bad))


def test_wrong_palette_detected(plan: dict, deck: dict) -> None:
    bad = copy.deepcopy(deck)
    bad["palette"]["accent"] = "#000000"
    problems = cross_checks.check_palette(plan, bad)
    assert "palette" in ids(problems)
    assert has_errors(problems)


def test_era_mismatch_detected(plan: dict, deck: dict) -> None:
    bad = copy.deepcopy(deck)
    bad["era"] = "고려"
    assert "palette" in ids(cross_checks.check_palette(plan, bad))
