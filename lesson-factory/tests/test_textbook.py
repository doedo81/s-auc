"""교과서 대조 검증.

담임 요구(2026-07-29): **"교과서 학습목표 일치시키고. 지금은 사회 교과서만 있는데
계속 보충해줄게."**

'계속 보충해줄게' 가 설계를 정했다 — **없는 과목이 있는 것이 정상**이어야 한다.
미등록을 실패로 만들면 다른 과목을 시작할 수 없고, 그러면 등록부를 지어내서 채우게 된다.
그건 CLAUDE.md B-1(성취기준 지어내기 금지)이 막으려던 바로 그 일이다.

LLM 을 호출하지 않는다.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from checks import Problem, has_errors  # noqa: E402
from checks import textbook_checks  # noqa: E402

CONTRACTS = ROOT / "contracts"
FIXTURES = ROOT / "tests" / "fixtures"
REGISTRY = ROOT / "curriculum" / "textbook"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ids(problems: list[Problem]) -> set[str]:
    return {p.check for p in problems}


@pytest.fixture
def plan() -> dict:
    return load(FIXTURES / "사회-5-2-2단원-1차시.plan.json")


# --------------------------------------------------------------- 등록부 자체

def test_registry_schema_is_wellformed() -> None:
    Draft202012Validator.check_schema(load(CONTRACTS / "textbook.schema.json"))


@pytest.mark.parametrize("path", sorted(REGISTRY.glob("*.json")))
def test_every_registry_validates(path: Path) -> None:
    """등록부가 늘어나도 형식이 어긋나지 않게 — 새 파일이 들어오면 자동으로 검사된다."""
    Draft202012Validator(load(CONTRACTS / "textbook.schema.json")).validate(load(path))


@pytest.mark.parametrize("path", sorted(REGISTRY.glob("*.json")))
def test_registry_filename_matches_content(path: Path) -> None:
    """파일명이 조회 키다. `사회-5-2.json` 이 실과 내용을 담고 있으면 영원히 못 찾는다."""
    data = load(path)
    assert path.stem == f"{data['subject']}-{data['grade']}-{data['semester']}"


@pytest.mark.parametrize("path", sorted(REGISTRY.glob("*.json")))
def test_registry_periods_are_unique(path: Path) -> None:
    """같은 차시가 두 번 등록되면 어느 쪽이 진실인지 알 수 없다."""
    periods = [le["period"] for u in load(path)["units"] for le in u["lessons"]]
    assert len(periods) == len(set(periods)), [p for p in periods if periods.count(p) > 1]


@pytest.mark.parametrize("path", sorted(REGISTRY.glob("*.json")))
def test_registry_standards_exist(path: Path) -> None:
    """등록부의 성취기준도 NCIC DB 조회를 거친다 — 지어낼 자리를 남기지 않는다."""
    db = ROOT / "curriculum" / "standards.sqlite"
    if not db.exists():
        pytest.skip("scripts/seed_standards.py 를 먼저 실행")

    import sqlite3

    conn = sqlite3.connect(db)
    try:
        for unit in load(path)["units"]:
            for code in unit.get("standards") or []:
                row = conn.execute("SELECT 1 FROM standards WHERE code = ?", (code,)).fetchone()
                assert row is not None, f"{path.name}: 성취기준 {code} 가 DB에 없음"
    finally:
        conn.close()


def test_verified_requires_textbook_source() -> None:
    """'대조했다'고 표시하려면 출처가 교과서여야 한다.

    선생님 자료를 보고 '확인함'이라 적으면 확인이 아니다. 지금 사회 등록부는
    학습지 PDF 에서 옮긴 것이라 전부 verified=false 다.
    """
    validator = Draft202012Validator(load(CONTRACTS / "textbook.schema.json"))
    bad = load(REGISTRY / "사회-5-2.json")
    lesson = bad["units"][0]["lessons"][0]
    lesson["verified"] = True  # source 는 여전히 학습지 PDF
    assert list(validator.iter_errors(bad))


def test_사회_registry_is_honest_about_coverage() -> None:
    """지금 등록된 것은 2-1 소단원 7차시뿐이고, 전부 미대조다."""
    data = load(REGISTRY / "사회-5-2.json")
    lessons = [le for u in data["units"] for le in u["lessons"]]
    assert len(lessons) == 7
    assert all(not le["verified"] for le in lessons)
    assert all("학습지" in le["source"] for le in lessons)


# ------------------------------------------------------------------ 조회 동작

def test_unregistered_subject_only_warns(plan: dict) -> None:
    """★ '계속 보충해줄게' 를 지탱하는 동작.

    실과·국어·수학은 아직 교과서가 없다. 없는 것을 실패로 만들면 다른 과목을
    시작조차 못 하고, 그러면 등록부를 지어내서 채우게 된다.
    """
    실과 = load(FIXTURES / "실과-5-2-5단원-4차시.plan.json")
    problems = textbook_checks.run_all(실과)
    assert "textbook" in ids(problems)
    assert not has_errors(problems)
    assert any("등록되지 않음" in p.message for p in problems)


def test_unregistered_period_only_warns() -> None:
    """등록된 과목이라도 아직 안 채운 차시는 경고까지다."""
    사회9 = load(FIXTURES / "사회-5-2-2단원-9차시.plan.json")
    problems = textbook_checks.run_all(사회9)
    assert not has_errors(problems)
    assert any("9/14 차시가 없음" in p.message for p in problems)


def test_registered_lesson_is_looked_up(plan: dict) -> None:
    registry = textbook_checks.load_registry("사회", 5, 2)
    lesson = textbook_checks.find_lesson(registry, "1/14")
    assert lesson["pages"] == [70, 75]
    assert lesson["title"] == "단원 열기 — 유교 문화와 조선"


# --------------------------------------------------- 미대조 → 경고, 대조 → 실패

def test_aligned_objective_passes(plan: dict) -> None:
    """★ 담임 지시로 정렬한 결과 (2026-07-29 "교과서 학습목표 일치시키고").

    검사가 세안의 '단원 탐구 질문' 을 잡아냈고, 약안·학습지와 같은 쪽으로 통일했다.
    이제 지도안이 등록부와 같은 문장을 쓴다.
    """
    assert textbook_checks.check_textbook_objective(plan) == []


def test_unverified_mismatch_only_warns(plan: dict) -> None:
    """등록부가 아직 교과서 원본 대조 전이면 어긋나도 경고까지다."""
    bad = copy.deepcopy(plan)
    bad["objectives"][0]["text"] = "조선 시대 사람들의 옷차림을 설명할 수 있다."
    problems = textbook_checks.check_textbook_objective(bad)
    assert "textbook" in ids(problems)
    assert not has_errors(problems)
    assert any("대조 전이라 경고로 둔다" in p.message for p in problems)


def test_verified_mismatch_fails(plan: dict, tmp_path: Path) -> None:
    """교과서를 펴서 확인한 값과 어긋나면 지도안이 틀린 것이다 — 실패."""
    data = load(REGISTRY / "사회-5-2.json")
    lesson = data["units"][0]["lessons"][0]
    lesson["verified"] = True
    lesson["source"] = "교과서 70쪽"
    (tmp_path / "사회-5-2.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    bad = copy.deepcopy(plan)
    bad["objectives"][0]["text"] = "조선 시대 사람들의 옷차림을 설명할 수 있다."
    problems = textbook_checks.check_textbook_objective(bad, root=tmp_path)
    assert has_errors(problems)


def test_matching_objective_passes(plan: dict, tmp_path: Path) -> None:
    """지도안을 교과서 문구로 맞추면 통과한다 — 이게 '일치시킨다'의 결과다."""
    data = load(REGISTRY / "사회-5-2.json")
    lesson = data["units"][0]["lessons"][0]
    lesson["verified"] = True
    lesson["source"] = "교과서 70쪽"
    (tmp_path / "사회-5-2.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    fixed = copy.deepcopy(plan)
    fixed["objectives"][0]["text"] = lesson["objective"]
    assert textbook_checks.check_textbook_objective(fixed, root=tmp_path) == []


def test_punctuation_is_not_a_mismatch(plan: dict, tmp_path: Path) -> None:
    """쉼표·띄어쓰기 차이로 실패시키지 않는다 (cross_checks 와 같은 기준)."""
    data = load(REGISTRY / "사회-5-2.json")
    lesson = data["units"][0]["lessons"][0]
    lesson["verified"] = True
    lesson["source"] = "교과서 70쪽"
    (tmp_path / "사회-5-2.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    fixed = copy.deepcopy(plan)
    fixed["objectives"][0]["text"] = lesson["objective"].replace(" ", "").replace(".", "")
    assert textbook_checks.check_textbook_objective(fixed, root=tmp_path) == []


def test_page_mismatch_detected(plan: dict, tmp_path: Path) -> None:
    """교과서 쪽이 어긋나면 학생이 다른 쪽을 편다."""
    data = load(REGISTRY / "사회-5-2.json")
    lesson = data["units"][0]["lessons"][0]
    lesson["verified"] = True
    lesson["source"] = "교과서 70쪽"
    lesson["objective"] = plan["objectives"][0]["text"]
    (tmp_path / "사회-5-2.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    bad = copy.deepcopy(plan)
    bad["meta"]["textbook_pages"] = [76, 79]
    problems = textbook_checks.check_textbook_objective(bad, root=tmp_path)
    assert any("교과서 쪽이 다름" in p.message for p in problems)
    assert has_errors(problems)


# ---------------------------------------- 성취기준 DB 가 못 잡던 구멍이 메워진다

def test_wrong_unit_standard_now_caught(plan: dict) -> None:
    """★ 여기가 이 등록부의 진짜 값어치다.

    성취기준 DB 는 '코드가 실재하는가' 까지만 봤다. 같은 사회 과목 안에서 엉뚱한
    단원의 코드를 붙인 것은 못 잡았다(test_existing_but_wrong_standard_is_NOT_caught).
    교과서 등록부가 '이 차시는 어느 소단원인가'를 알고 있으므로 그 구멍이 메워진다.
    """
    bad = copy.deepcopy(plan)
    bad["standards"] = ["6사05-02"]  # 실재하는 사회 코드지만 2-2(조선 후기) 것이다

    problems = textbook_checks.check_textbook_standards(bad)
    assert "textbook_standards" in ids(problems)
    assert has_errors(problems)


def test_right_standard_passes(plan: dict) -> None:
    assert textbook_checks.check_textbook_standards(plan) == []


def test_standards_check_skipped_for_unregistered() -> None:
    """등록부가 없으면 이 검사도 조용히 지나간다."""
    실과 = load(FIXTURES / "실과-5-2-5단원-4차시.plan.json")
    assert textbook_checks.check_textbook_standards(실과) == []
