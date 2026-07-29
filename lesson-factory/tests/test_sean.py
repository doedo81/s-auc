"""세안 생성 검증 — 스키마 · 기계 검사 · 렌더러.

담임 판정(2026-07-29): **"약안 말고 세안으로 짜줘. 약안은 게임 내용을 모르겠더라."**

같은 게임을 두 문서가 이렇게 다르게 적는다.

    약안  '유교 문화 축제에서 동생 찾기' 미션 — 단원 그림 단서로 추측   (26자)
    세안  동생 이름 태웅이 · 단서는 가족 4명의 말 · 답은 어느 체험관 ·
          절차 ①단서 받고 문장틀로 쓰기 → ②시계 방향으로 넘기기 → ③친구 답에 더하기

여기의 검사들은 전부 그 차이를 지키기 위한 것이다.
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

from checks import Problem, has_errors, needs_review  # noqa: E402
from checks import cross_checks, plan_checks, print_checks  # noqa: E402
from render import sean  # noqa: E402

CONTRACTS = ROOT / "contracts"
FIXTURES = ROOT / "tests" / "fixtures"
DB = ROOT / "curriculum" / "standards.sqlite"
TRACE = "사회-5-2-2단원-1차시"


@pytest.fixture
def plan() -> dict:
    return json.loads((FIXTURES / f"{TRACE}.plan.json").read_text(encoding="utf-8"))


@pytest.fixture
def worksheet() -> dict:
    return json.loads((FIXTURES / f"{TRACE}.worksheet.json").read_text(encoding="utf-8"))


def validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads((CONTRACTS / "lesson_plan.schema.json").read_text(encoding="utf-8")))


def _rejects(doc: dict) -> None:
    assert list(validator().iter_errors(doc)), "스키마가 불량 데이터를 통과시켰다"


def ids(problems: list[Problem]) -> set[str]:
    return {p.check for p in problems}


# ------------------------------------------------------------------ 실물 통과

def test_real_sean_validates(plan: dict) -> None:
    validator().validate(plan)


def test_real_sean_has_no_errors(plan: dict) -> None:
    """실물 세안에 오류가 없어야 한다. 경고는 아래에서 따로 확인한다."""
    problems = plan_checks.run_all(plan, DB if DB.exists() else None)
    assert not has_errors(problems), [str(p) for p in problems]


def test_real_sean_has_no_check_errors(plan: dict, worksheet: dict) -> None:
    """지도안↔활동지 교차 검사도 오류 없이 통과한다 (덱은 아직 없다)."""
    problems = cross_checks.run_all(plan, worksheet)
    assert not has_errors(problems), [str(p) for p in problems]


def test_minutes_and_slides_line_up(plan: dict) -> None:
    """세안이 약안보다 믿을 만하다는 증거 — 약안은 4+12+12+8=36분이라 이 검사에 걸린다."""
    assert sum(a["minutes"] for a in plan["activities"]) == plan["meta"]["minutes"] == 40
    assert plan_checks.check_slide_ranges(plan) == []


# --------------------------------------------------- 세안이라야 하는 것 (스키마)

def test_rejects_game_without_stem_or_script(plan: dict) -> None:
    """절차만 있고 학생 문장틀도 교사 대사도 없으면 굴릴 수 없다."""
    bad = copy.deepcopy(plan)
    game = bad["activities"][1]["game"]
    game["sentence_stem"] = None
    del game["teacher_script"]
    _rejects(bad)


def test_rejects_game_without_premise(plan: dict) -> None:
    """이름만 있는 게임 — 약안이 딱 이 상태였다."""
    bad = copy.deepcopy(plan)
    del bad["activities"][1]["game"]["premise"]
    _rejects(bad)


def test_accepts_game_without_scoring(plan: dict) -> None:
    """점수와 승리 조건은 선택이다.

    실물 활동1이 의도적으로 비워 둔 자리다 —
    ※정답 찾기보다 "그림 속 유교 문화 요소 발견"이 목적.
    억지로 요구하면 확산적 활동이 정답 맞히기로 변질된다.
    """
    game = next(a["game"] for a in plan["activities"] if a["id"] == "A2")
    assert game["scoring"] is None and game["win_condition"] is None
    validator().validate(plan)


def test_rejects_unknown_speaker(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["activities"][0]["blocks"][0]["lines"][0]["speaker"] = "교사"
    _rejects(bad)


def test_rejects_상중하_with_도달_levels(plan: dict) -> None:
    """척도를 골라 놓고 다른 표기를 섞으면 문서에 절반만 인쇄된다."""
    bad = copy.deepcopy(plan)
    bad["assessment"]["observations"][0]["levels"] = {"도달": "가", "부분도달": "나", "지원필요": "다"}
    _rejects(bad)


def test_accepts_single_criterion_without_levels(plan: dict) -> None:
    """실물 세안의 사회적 기술 행은 상/중/하 없이 한 줄이다. 없는 수준을 지어내지 않는다."""
    obs = plan["assessment"]["observations"][1]
    assert "levels" not in obs and obs["criterion"]
    validator().validate(plan)


def test_rejects_observation_with_neither(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    del bad["assessment"]["observations"][1]["criterion"]
    _rejects(bad)


def test_accepts_open_materials(plan: dict) -> None:
    """폐쇄 enum 이면 실물이 안 들어간다 — '질문 띠지'·'OX 이동판(동물 카드)'·'단서 종이'."""
    materials = {m for a in plan["activities"] for m in a["materials"]}
    assert "질문 띠지" in materials and "단서 종이" in materials


# ---------------------------------------------------------- 세안 검사 (기계)

def test_missing_teacher_dialogue_detected(plan: dict) -> None:
    """세안인데 교사 대사가 없으면 잡는다."""
    bad = copy.deepcopy(plan)
    for block in bad["activities"][1]["blocks"]:
        block["lines"] = [ln for ln in block.get("lines", []) if ln["speaker"] != "T"]
    problems = plan_checks.check_dialogue_present(bad)
    assert "dialogue" in ids(problems)
    assert any("A2" in p.message for p in problems)


def test_half_sean_detected(plan: dict) -> None:
    """절반만 세안인 문서가 가장 나쁘다 — 교사가 어디까지 대본이 있는지 모른다."""
    bad = copy.deepcopy(plan)
    del bad["activities"][3]["blocks"]
    assert "dialogue" in ids(plan_checks.check_dialogue_present(bad))


def test_약안_skips_dialogue_check(plan: dict) -> None:
    """blocks 를 아예 안 쓰면 약안으로 보고 검사하지 않는다 (기존 픽스처 보호)."""
    약안 = copy.deepcopy(plan)
    for a in 약안["activities"]:
        a.pop("blocks", None)
    assert plan_checks.check_dialogue_present(약안) == []


def test_unrunnable_game_detected(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    game = bad["activities"][1]["game"]
    game["sentence_stem"] = None
    game["teacher_script"] = []
    assert "game_runnable" in ids(plan_checks.check_game_runnable(bad))


def test_game_material_omission_detected(plan: dict) -> None:
    """★ 실물에서 실제로 빠져 있던 것.

    원본 세안 활동1은 '단서 종이'로 굴러가는데 자료(★) 칸에도, 머리표 '학습 자료'
    에도 단서 종이가 없다. 수업 전날 인쇄물을 준비하는 사람은 자료 칸만 본다.
    픽스처는 이 누락을 고쳐 넣은 것이며, 여기서는 되돌려 검사가 잡는지 본다.
    """
    original = copy.deepcopy(plan)
    a2 = next(a for a in original["activities"] if a["id"] == "A2")
    a2["materials"] = [m for m in a2["materials"] if m != "단서 종이"]

    problems = plan_checks.check_game_materials(original)
    assert "game_materials" in ids(problems)
    assert any("단서 종이" in p.message for p in problems)


def test_game_materials_tolerate_notation(plan: dict) -> None:
    """'★단서 종이(모둠별)' 와 '단서 종이' 를 같은 것으로 본다 — 표기 차이로 오탐하지 않는다."""
    ok = copy.deepcopy(plan)
    a2 = next(a for a in ok["activities"] if a["id"] == "A2")
    a2["materials"] = ["★단서 종이(모둠별)" if m == "단서 종이" else m for m in a2["materials"]]
    assert plan_checks.check_game_materials(ok) == []


def test_competition_policy_contradiction_detected(plan: dict) -> None:
    """'순위 공개 금지'라고 써 놓고 순위를 공개하는 게임을 넣는 일을 막는다.

    담임 결정으로 경쟁 정책을 차시마다 고를 수 있게 한 대신, 이 모순은 기계가 잡는다.
    """
    bad = copy.deepcopy(plan)
    bad["prohibitions"] = ["속도 경쟁·순위·탈락 언어 사용 금지"]
    bad["activities"][3]["game"]["competition_policy"] = "순위공개"
    problems = plan_checks.check_competition_policy(bad)
    assert "competition_policy" in ids(problems)
    assert has_errors(problems)


def test_competition_policy_ok_without_prohibition(plan: dict) -> None:
    """금지사항이 없으면 순위공개도 통과한다 — 정책은 차시마다 고르는 것이지 금지가 아니다."""
    ok = copy.deepcopy(plan)
    ok["activities"][3]["game"]["competition_policy"] = "순위공개"
    assert plan_checks.check_competition_policy(ok) == []


def test_slide_overlap_detected(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["activities"][2]["slide_range"] = [7, 10]  # 활동1이 5~7 이므로 겹침
    problems = plan_checks.check_slide_ranges(bad)
    assert "slide_range" in ids(problems)
    assert has_errors(problems)


def test_slide_gap_warns(plan: dict) -> None:
    bad = copy.deepcopy(plan)
    bad["activities"][3]["slide_range"] = [15, 16]
    problems = plan_checks.check_slide_ranges(bad)
    assert "slide_range" in ids(problems)
    assert not has_errors(problems)


# ---------------------------------------------------------------- 렌더러

def test_notation_matches_real_document(plan: dict) -> None:
    """표기 규약이 실물과 같은가 — T/S 는 콜론 없이, 절차는 ①→②, 자료는 ★, 유의점은 ※."""
    cell = sean.activity_cell(plan["activities"][1])
    assert "▶ 교과서 72~73쪽 축제 그림 살펴보기" in cell
    assert "\nT 교과서 72~73쪽을 펴 보세요." in cell
    assert "T:" not in cell and "S:" not in cell
    assert "① 단서 종이를 받으면" in cell and " → ② 시계 방향으로 넘기기" in cell

    materials = sean.materials_cell(plan["activities"][1])
    assert materials.startswith("★교과서 72~73쪽")
    assert "※한 사람이 독점하지 않게" in materials


def test_narration_line_has_no_speaker_mark(plan: dict) -> None:
    """학습 문제는 발화가 아니므로 T/S 없이 그대로 인쇄된다."""
    cell = sean.activity_cell(plan["activities"][0])
    assert "\n유교 문화가 조선 사람들의 생활에 어떤 영향을" in cell
    assert "— 유교 문화가" not in cell


def test_header_shows_both_page_ranges(plan: dict) -> None:
    pairs = dict((row[2], row[3]) for row in sean.header_pairs(plan, DB if DB.exists() else None))
    assert pairs["교과서"] == "70~75쪽 (지도서 156~163쪽)"
    assert pairs["차시"] == "1/14차시 (소단원 1/7)"


@pytest.mark.skipif(not DB.exists(), reason="scripts/seed_standards.py 를 먼저 실행")
def test_standard_text_comes_from_db(plan: dict) -> None:
    """CLAUDE.md B-1 — 성취기준 문구는 DB 에서만 온다."""
    line = sean.standard_lines(plan, DB)[0]
    assert line.startswith("[6사05-01] ")
    assert "유교 문화가 미친 영향" in line


def test_standard_text_omitted_when_db_missing(plan: dict) -> None:
    """조회에 실패하면 코드만 인쇄한다. 지어내지 않는다."""
    assert sean.standard_lines(plan, Path("/nonexistent.sqlite")) == ["[6사05-01]"]


def test_학습자료_collects_game_materials(plan: dict) -> None:
    """머리표 '학습 자료' 가 게임 준비물까지 모은다 — 실물이 놓친 지점이다."""
    materials = sean.all_materials(plan)
    assert "단서 종이" in materials
    assert "질문 띠지" in materials
    assert materials.count("수업 슬라이드") == 1  # 슬라이드는 한 벌로 접는다


def test_board_plan_is_derived_from_body(plan: dict) -> None:
    """판서 계획은 파생 뷰다 — 별도 입력이 없으므로 본문과 어긋날 수 없다."""
    lines = sean.board_plan(plan)
    assert lines[0].startswith("[2단원] 달라지는 시대, 변화하는 생활 모습 — 1차시")
    assert any("공부할 문제:" in ln for ln in lines)
    assert any("(모둠 시계돌리기)" in ln and "(돌아가며 쓰기)" in ln for ln in lines)
    assert any("조선은 유교를 바탕으로 세운 나라다." in ln for ln in lines)


def test_board_plan_follows_activity_edit(plan: dict) -> None:
    """본문의 협동 구조를 바꾸면 판서 계획이 따라 바뀐다."""
    edited = copy.deepcopy(plan)
    edited["activities"][1]["kagan_structure"] = "브레인라이팅"
    assert any("(브레인라이팅)" in ln for ln in sean.board_plan(edited))


def test_markdown_has_all_seven_sections(plan: dict) -> None:
    text = sean.render_markdown(plan, DB if DB.exists() else None)
    for section in ("교수·학습 과정안 (세안)", "■ 본시 교수·학습 과정", "■ 평가 계획",
                    "■ 판서 계획", "■ 지도상의 유의점"):
        assert section in text, section
    assert text.rstrip().endswith("신리초 5-5 수업용 · 외부 배포 금지")


# ------------------------------------------------------- 활동지 골격 (실물 PDF)
#
# 사회/활동지/2단원_2-1_유교조선_학습지.pdf 1쪽에서 옮긴 것.
# 매 페이지가 같은 골격을 쓰고 아래쪽 활동칸만 구조에 따라 바뀐다.

def test_worksheet_has_real_skeleton(worksheet: dict) -> None:
    assert worksheet["objective"].startswith("유교 문화가 조선 사람들의")
    assert worksheet["textbook_pages"] == [70, 75]
    assert worksheet["structure_label"] == "모둠 시계돌리기·돌아가며 쓰기"
    assert worksheet["hints"]["slow"] and worksheet["hints"]["fast"]
    assert len(worksheet["closing"]["ox_statements"]) == 4
    assert "최종 도착한 동물" in worksheet["closing"]["result_line"]


def test_worksheet_ox_carries_no_answers(worksheet: dict) -> None:
    """제작 규칙 §4: '활동지에는 정답(O/X)을 표시하지 않는다 — 문제만!'

    스키마가 ox_statements 를 문자열 배열로 둬서 정답을 담을 자리를 아예 없앴다.
    실물 약안 ④ 에는 '(O)' '(X — 한양)' 가 붙어 있는데, 그건 교사용이다.
    """
    assert cross_checks.check_worksheet_answers_hidden(worksheet) == []
    for statement in worksheet["closing"]["ox_statements"]:
        assert "(O)" not in statement and "(X" not in statement


def test_ox_answer_leak_into_worksheet_detected(worksheet: dict) -> None:
    """약안 ④ 를 그대로 복사해 오면 정답이 딸려 온다 — 실제로 일어나기 쉬운 실수."""
    bad = copy.deepcopy(worksheet)
    bad["closing"]["ox_statements"][2] = "조선의 도읍은 개경이었다. (X — 한양)"
    problems = cross_checks.check_worksheet_answers_hidden(bad)
    assert "worksheet_answers" in ids(problems)
    assert has_errors(problems)


def test_textbook_page_drift_detected(plan: dict, worksheet: dict) -> None:
    """활동지 교과서 쪽이 지도안과 어긋나면 학생이 다른 쪽을 편다."""
    bad = copy.deepcopy(worksheet)
    bad["textbook_pages"] = [76, 79]
    problems = cross_checks.check_worksheet_skeleton(plan, bad)
    assert "worksheet_skeleton" in ids(problems)
    assert has_errors(problems)


def test_closing_sentence_drift_detected(plan: dict, worksheet: dict) -> None:
    """학생이 쓰는 빈칸 문장이 지도안과 다르면 정리 단계가 어긋난다."""
    bad = copy.deepcopy(worksheet)
    bad["closing"]["sentence_prompt"] = "조선은 ____의 나라다."
    problems = cross_checks.check_worksheet_skeleton(plan, bad)
    assert "worksheet_skeleton" in ids(problems)
    assert has_errors(problems)


def test_objective_now_aligned_across_documents(plan: dict, worksheet: dict) -> None:
    """★ 담임 지시로 정렬된 것 (2026-07-29 "교과서 학습목표 일치시키고").

    원본 세안 머리표는 '…알고, **단원** 탐구 질문을' 이었고 약안·학습지는
    '…알고 탐구 질문을' 이었다. 검사가 이 차이를 잡아냈고, 두 곳이 일치하는 쪽으로
    통일했다. 이제 지도안 · 활동지 · 교과서 등록부 셋이 같은 문장을 쓴다.
    """
    assert plan["objectives"][0]["text"] == worksheet["objective"]
    assert "단원 탐구" not in plan["objectives"][0]["text"]
    assert cross_checks.check_worksheet_skeleton(plan, worksheet) == []


def test_punctuation_difference_is_not_drift(plan: dict, worksheet: dict) -> None:
    ok = copy.deepcopy(worksheet)
    ok["objective"] = plan["objectives"][0]["text"].replace(",", "").replace(" ", "")
    assert not any(
        "학습 목표 문구가 다름" in p.message
        for p in cross_checks.check_worksheet_skeleton(plan, ok)
    )


def test_objective_wording_drift_still_detected(plan: dict, worksheet: dict) -> None:
    """정렬했다고 검사를 치우지 않는다 — 다시 어긋나면 다시 잡혀야 한다."""
    bad = copy.deepcopy(worksheet)
    bad["objective"] = "유교 문화가 조선 사람들의 생활에 영향을 주었음을 알고, 단원 탐구 질문을 만들 수 있다."
    problems = cross_checks.check_worksheet_skeleton(plan, bad)
    assert "worksheet_skeleton" in ids(problems)
    assert not has_errors(problems)


def test_skeleton_absence_only_warns(plan: dict, worksheet: dict) -> None:
    """골격이 통째로 없어도 경고까지다 — 실과처럼 규칙이 다른 과목을 막지 않는다."""
    bare = copy.deepcopy(worksheet)
    for field in ("objective", "textbook_pages", "hints", "closing"):
        bare.pop(field)
    problems = cross_checks.check_worksheet_skeleton(plan, bare)
    assert len(problems) == 4
    assert not has_errors(problems)


def test_worksheet_now_covers_the_활동지_gap(plan: dict) -> None:
    """활동지를 찾기 전에는 이 차시가 '활동지 없음' 경고를 달고 있었다.

    실물 학습지 PDF 를 찾아 넣으면서 경고가 사라졌다 — 경고가 옳았다는 뜻이다.
    """
    assert plan_checks.check_templated_structure_has_worksheet(plan) == []


# ------------------------------------------------------- 게임 정답 (교사용)
#
# 담임 확인(2026-07-29): 답은 **선비 문화 체험관**.
# 물어봐야 했다는 것 자체가 스키마의 구멍이었다 — answer_format 은 '○○ 체험관' 이라는
# 틀만 알려 줄 뿐 무엇이 답인지 말해 주지 않는다. 게임 명세만 읽은 교사가 학생 답을
# 판정할 수 없으니 R8('게임 부분만 따로 읽어도 굴릴 수 있는가')이 거기서 무너진다.

def test_game_answer_is_recorded(plan: dict) -> None:
    game = next(a["game"] for a in plan["activities"] if a["id"] == "A2")
    assert game["answer_format"] == "○○ 체험관"
    assert game["answer"] == "선비 문화 체험관"


def test_answer_format_without_answer_goes_to_teacher(plan: dict) -> None:
    """답의 형태만 정하고 정답을 비워 두면 담임 확인으로 올린다.

    실패가 아니라 review 다 — 확산적 활동은 정답이 없을 수 있고, 그 판단은 사람이 한다.
    """
    bad = copy.deepcopy(plan)
    bad["activities"][1]["game"]["answer"] = None
    problems = plan_checks.check_game_runnable(bad)
    assert "game_runnable" in ids(problems)
    assert not has_errors(problems)
    assert needs_review(problems)


def test_divergent_game_needs_no_answer(plan: dict) -> None:
    """답의 형태 자체가 없으면 정답도 요구하지 않는다 — 정답이 목적이 아닌 활동을 막지 않는다."""
    ok = copy.deepcopy(plan)
    game = ok["activities"][1]["game"]
    game["answer_format"] = None
    game["answer"] = None
    assert not any("정답 자체가 없음" in p.message for p in plan_checks.check_game_runnable(ok))


def test_game_answer_leak_into_worksheet_detected(plan: dict, worksheet: dict) -> None:
    """★ 정답이 학생 활동지로 새는 것을 막는다.

    활동지를 지도안에서 파생시키다 보면 그대로 흘러 들어가기 쉽다.
    OX 정답에 이미 같은 규칙이 있고(제작 규칙 §4), 게임 정답이라고 다를 이유가 없다.
    """
    bad = copy.deepcopy(worksheet)
    bad["items"][0]["prompt"] = "태웅이는 선비 문화 체험관에 있어요. 왜 그럴까요? →"
    problems = cross_checks.check_game_answer_hidden(plan, bad)
    assert "game_answer" in ids(problems)
    assert has_errors(problems)


def test_game_answer_stays_off_the_real_worksheet(plan: dict, worksheet: dict) -> None:
    assert cross_checks.check_game_answer_hidden(plan, worksheet) == []


def test_teacher_notes_may_hold_the_answer(plan: dict, worksheet: dict) -> None:
    """교사용 자리에는 정답이 있어도 된다 — 학생 인쇄본에 안 나가기 때문이다."""
    ok = copy.deepcopy(worksheet)
    ok["teacher_notes"].append("정답: 선비 문화 체험관")
    assert cross_checks.check_game_answer_hidden(plan, ok) == []


# ------------------------------------------------------------------ 인쇄량
#
# 담임 요구(2026-07-29): "애들한테 나눠줄 때는 최대한 한 장이나 두 장 양면 복사할 수 있게.
# 더 많으면 나한테 좀 보여줘. 그래야 수정 좀 하고 나눠주게. 안 그러면 인쇄량이 너무 많아지지.
# 모둠은 여섯 개니까 여섯 모둠한테 나눠줄 때는 다양하게 나눠줄 순 있어."

def test_real_worksheet_fits_one_sheet(plan: dict, worksheet: dict) -> None:
    """실물 학습지는 한 차시가 한 면이다 (제작 규칙 §3-7)."""
    assert worksheet["distribution"] == "개인"
    assert worksheet["pages"] == 1
    assert print_checks.run_all(plan, worksheet) == []


def test_over_two_pages_goes_to_teacher(plan: dict, worksheet: dict) -> None:
    """★ 개인 배부가 양면 한 장을 넘으면 담임 확인으로 올린다.

    실패가 아니라 review 다. 자를 곳을 정하는 것은 수업을 아는 사람의 판단이고,
    기계가 임의로 자르면 학습에 필요한 칸이 날아간다. 막지 않고 보여 준다.
    """
    bad = copy.deepcopy(worksheet)
    bad["pages"] = 3
    problems = print_checks.run_all(plan, bad)

    assert "print_budget" in ids(problems)
    assert not has_errors(problems)
    assert needs_review(problems)


def test_two_pages_duplex_is_fine(plan: dict, worksheet: dict) -> None:
    """양면 한 장까지는 그대로 나간다 — 실과 4차시가 이 경우다."""
    ok = copy.deepcopy(worksheet)
    ok["pages"] = 2
    assert print_checks.run_all(plan, ok) == []


def test_group_distribution_has_no_page_limit(plan: dict, worksheet: dict) -> None:
    """모둠 배부는 분량을 조이지 않는다 — 여섯 부만 찍으면 되고, 모둠마다 달라도 된다."""
    group = copy.deepcopy(worksheet)
    group["distribution"] = "모둠"
    group["pages"] = 5
    assert print_checks.run_all(plan, group) == []


def test_sheets_reflect_six_groups(plan: dict, worksheet: dict) -> None:
    """모둠 수는 담임 확인값 6개. 인쇄량이 실제로 그만큼만 나온다."""
    assert plan["group_setup"]["group_count"] == 6

    group = copy.deepcopy(worksheet)
    group["distribution"] = "모둠"
    assert print_checks.sheets_needed(plan, group, class_size=24)["sheets"] == 6

    personal = print_checks.sheets_needed(plan, worksheet, class_size=24)
    assert personal["sheets"] == 24


def test_duplex_halves_the_paper(plan: dict, worksheet: dict) -> None:
    """2면을 양면으로 찍으면 종이는 한 장. 이게 '두 장 양면 복사'의 뜻이다."""
    two = copy.deepcopy(worksheet)
    two["pages"] = 2
    assert print_checks.sheets_needed(plan, two, class_size=24)["sheets"] == 24

    two["duplex"] = False
    assert print_checks.sheets_needed(plan, two, class_size=24)["sheets"] == 48


def test_summary_line_is_readable(plan: dict, worksheet: dict) -> None:
    """담임 승인 카드에 그대로 들어가는 줄."""
    assert print_checks.summary_line(plan, worksheet, 24) == "개인 24부 × 1면 단면 = 종이 24장"


def test_group_count_defaults_to_six(worksheet: dict) -> None:
    """지도안에 모둠 수가 없어도 우리 반 기본값 6으로 센다."""
    bare = {"group_setup": {}}
    group = copy.deepcopy(worksheet)
    group["distribution"] = "모둠"
    assert print_checks.sheets_needed(bare, group, class_size=24)["copies"] == 6


def test_unknown_severity_rejected() -> None:
    """심각도 3단계 밖의 값이 들어오면 즉시 터진다 — 조용히 error 로 취급되면 안 된다."""
    with pytest.raises(ValueError):
        Problem("x", "y", severity="치명")


def test_docx_builds() -> None:
    docx = pytest.importorskip("docx")  # noqa: F841
    plan = json.loads((FIXTURES / f"{TRACE}.plan.json").read_text(encoding="utf-8"))
    from render import sean_docx

    doc = sean_docx.build(plan, DB if DB.exists() else None)
    tables = doc.tables
    assert len(tables) == 3                      # 머리표 · 본시 과정 · 평가 계획
    assert len(tables[1].rows) == 1 + len(plan["activities"])
    assert tables[1].rows[0].cells[2].text.startswith("교수·학습 활동")
