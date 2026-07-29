"""2차시 세안 — **처음으로 옮겨 적지 않고 만든 산출물**.

1차시 픽스처는 실물 `사회_2-1_1차시_세안.docx` 를 스키마로 옮긴 것이다. 이 파일이 검증하는
2차시는 다르다 — `agents/prompts/teacher_sean.md` 를 그대로 따라 약안·교과서 76~79쪽·
등록부에서 새로 짠 것이다. 그래서 **원본과 비교하는 시험이 없다.** 대신 프롬프트가 요구한
것들이 실제로 산출물에 있는지를 본다.

여기서 잡힌 실물 두 가지를 시험으로 고정한다.

1. 학습지는 건물 넷(보신각=신 포함)을 묻는데 **교과서 77쪽은 '인·의·예' 셋만** 찾게 한다.
2. 약안 ④의 OX 4문제는 2·3차시가 공유하는데 **3번이 서당(3차시 내용)** 이다.

둘 다 수업 중에야 드러났을 어긋남이고, 지금은 `cautions` 에 적혀 세안을 읽으면 보인다.
LLM 을 호출하지 않는다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from checks import has_errors, needs_review  # noqa: E402
from checks import cross_checks, plan_checks, print_checks, textbook_checks  # noqa: E402
from render import sean  # noqa: E402

CONTRACTS = ROOT / "contracts"
FIXTURES = ROOT / "tests" / "fixtures"
DB = ROOT / "curriculum" / "standards.sqlite"
TRACE = "사회-5-2-2단원-2차시"


@pytest.fixture
def plan() -> dict:
    return json.loads((FIXTURES / f"{TRACE}.plan.json").read_text(encoding="utf-8"))


@pytest.fixture
def worksheet() -> dict:
    return json.loads((FIXTURES / f"{TRACE}.worksheet.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 통과해야 한다

def test_plan_matches_schema(plan: dict) -> None:
    schema = json.loads((CONTRACTS / "lesson_plan.schema.json").read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(schema).iter_errors(plan))


def test_worksheet_matches_schema(worksheet: dict) -> None:
    schema = json.loads((CONTRACTS / "worksheet.schema.json").read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(schema).iter_errors(worksheet))


def test_no_problems_at_all(plan: dict, worksheet: dict) -> None:
    """1차시와 달리 경고조차 없어야 한다.

    1차시는 실물을 그대로 옮겼기 때문에 실물의 누락(게임 준비물 등)을 함께 가져왔다.
    2차시는 검사를 다 아는 상태에서 새로 짠 것이므로 깨끗하지 않을 이유가 없다.
    """
    problems = plan_checks.run_all(plan, DB if DB.exists() else None)
    problems += cross_checks.run_all(plan, worksheet)
    assert problems == [], [str(p) for p in problems]


def test_fits_one_page_per_student(plan: dict, worksheet: dict) -> None:
    """담임 요구: 개인 배부는 한 장. 24명이면 종이 24장."""
    assert not needs_review(print_checks.run_all(plan, worksheet))
    assert print_checks.summary_line(plan, worksheet, 24) == "개인 24부 × 1면 단면 = 종이 24장"


def test_minutes_are_forty_not_thirty_five(plan: dict) -> None:
    """약안 2차시는 5+15+7+8=35분이다. 세안으로 옮기며 전개2를 늘려 40분을 채웠다."""
    assert sum(a["minutes"] for a in plan["activities"]) == 40


def test_time_moved_to_the_slower_activity(plan: dict) -> None:
    """전개2가 전개1보다 길다.

    초안은 15/12 였다. 건물이 넷에서 셋으로 줄어 활동1이 짧아졌고, 담임 지적
    (2026-07-29 *"활동지 돌리는 게 시간이 더 오래 걸릴 수 있어"*)대로 그 3분을
    활동2로 옮겨 12/15 가 됐다. 각자의 활동지를 돌리면 종이가 네 배로 움직인다.
    """
    minutes = {a["stage_label"]: a["minutes"] for a in plan["activities"]}
    assert minutes["전개 활동2"] > minutes["전개 활동1"]
    assert [minutes[k] for k in ("도입", "전개 활동1", "전개 활동2", "정리")] == [5, 12, 15, 8]


# ------------------------------------------------------------------ 교과서·지도서 대조

def test_objective_comes_from_the_registry(plan: dict) -> None:
    """학습목표는 지어낸 것이 아니라 등록부에서 온다 (CLAUDE.md D-3-1)."""
    registry = textbook_checks.load_registry("사회", 5, 2)
    assert registry is not None
    lesson = textbook_checks.find_lesson(registry, "2/14")
    assert lesson is not None
    assert plan["objectives"][0]["text"] == lesson["objective"]
    assert plan["meta"]["textbook_pages"] == lesson["pages"]
    assert lesson["pages_verified"] is True


# ------------------------------------------------------------------ 게임만 읽어도 굴러가는가 (R8)

def test_game_is_runnable_from_the_game_block_alone(plan: dict) -> None:
    """담임 판정 기준. 게임 명세만 떼어 읽어도 교실에서 굴릴 수 있어야 한다."""
    game = next(a["game"] for a in plan["activities"] if a["id"] == "A2")
    assert game["answer"], "정답이 없으면 교사가 학생 답을 판정할 수 없다"
    assert game["rounds"] == len(game["answer"].split(" · ")) == 3
    assert game["steps"] and game["sentence_stem"]
    assert game["teacher_script"]
    assert game["competition_policy"] == "경쟁없음"


def test_game_answer_never_reaches_the_worksheet(worksheet: dict) -> None:
    """정답은 교사용에만. 학생용 인쇄면에 덕목 정답이 있으면 활동이 무의미해진다."""
    printed = json.dumps(
        {k: v for k, v in worksheet.items() if k not in ("teacher_notes", "items")},
        ensure_ascii=False,
    )
    for virtue in ("어짊", "의로움", "예의 바름", "믿음"):
        assert virtue not in printed
    for item in worksheet["items"]:
        assert "어짊" not in item["prompt"]      # example 은 교사용이라 예외


# ------------------------------------------------------------------ 실물에서 잡은 어긋남 2건

def test_follows_the_textbook_three_virtues(plan: dict, worksheet: dict) -> None:
    """교과서 77쪽대로 '인·의·예' 셋만 찾는다.

    초안은 학습지를 따라 보신각(신)까지 넷이었다. 신은 교과서에 없어 슬라이드로 따로
    보충해야 했고, 담임 판정(2026-07-29)으로 뺐다 — *"짝 점검이니까 셋으로 해도 됨"*.
    짝 점검에서 학습목표에 닿게 하는 것은 건물 수가 아니라 왜 그 덕목인지 말하는 쪽이다.

    뺀 흔적은 `cautions` 에 남긴다. 왜 넷이 아닌지 모르면 다음에 또 넷으로 돌아간다.
    """
    a2 = next(a for a in plan["activities"] if a["id"] == "A2")
    assert "보신각" not in a2["game"]["answer"]
    for item in worksheet["items"]:
        assert "보신각" not in (item.get("row_labels") or [])

    cautions = " ".join(a2["cautions"])
    assert "보신각" in cautions and "담임 판정" in cautions
    assert "숙정문" in cautions                  # '정'은 '지'가 아니다


def test_ox_question_moved_off_the_next_lesson(plan: dict, worksheet: dict) -> None:
    """약안 ④는 2·3차시가 OX 를 공유하는데 3번이 서당 — 2차시에는 아직 안 배웠다."""
    statements = worksheet["closing"]["ox_statements"]
    assert not any("서당" in s for s in statements)
    assert any("경복궁" in s for s in statements)
    cautions = " ".join(next(a for a in plan["activities"] if a["id"] == "A4")["cautions"])
    assert "서당" in cautions and "3차시" in cautions


def test_next_lesson_preview_still_points_at_서당(plan: dict) -> None:
    """서당 문항을 뺐다고 서당이 사라지면 안 된다 — 3차시로 미룬 것뿐이다."""
    assert "서당" in plan["next_period_preview"]


# ------------------------------------------------------------------ 인쇄를 줄인 설계 결정

def test_round_table_circulates_the_worksheet_itself(plan: dict, worksheet: dict) -> None:
    """돌아가며 쓰기에 모둠 기록지를 따로 찍지 않는다.

    케이건 카드는 '기록지 한 장' 이라고 하지만, 그러면 모둠 배부물이 하나 더 생긴다.
    각자의 활동지를 돌리면 네 바퀴 뒤 모두의 활동지에 까닭이 네 가지씩 남는다.
    """
    a3 = next(a for a in plan["activities"] if a["id"] == "A3")
    assert "기록지" not in " ".join(a3["materials"])
    reason = next(i for i in worksheet["items"] if i["id"] == "FOUNDING_REASON")
    assert reason["lines"] == 4 and reason["role"] == "모둠공유"


# ------------------------------------------------------------------ 렌더러

def test_header_lists_each_material_once(plan: dict) -> None:
    """머리표 '학습 자료' 는 차시 전체 목록이다.

    쪽수를 붙인 채 모으면 `교과서 76쪽 · 교과서 77~78쪽 · 교과서 78쪽` 이 되어 같은 물건이
    세 번 실린다. 쪽수는 '교과서' 칸과 활동별 ★ 에 이미 있다.
    """
    materials = sean.all_materials(plan)
    assert materials.count("교과서") == 1
    assert not any("쪽" in m for m in materials)
    assert materials.count("수업 슬라이드") == 1


def test_notation_marks_are_not_doubled(plan: dict) -> None:
    """★·※ 는 렌더러가 붙인다. 데이터가 달고 오면 `※★ …` 가 된다."""
    for activity in plan["activities"]:
        for line in sean.materials_cell(activity).splitlines():
            assert line[0] in "★※"
            assert line[1] not in "★※ "


def test_board_plan_names_both_activities(plan: dict) -> None:
    lines = sean.board_plan(plan)
    assert any("한양 도성 설계자" in ln and "짝 점검" in ln for ln in lines)
    assert any("돌아가며 쓰기" in ln for ln in lines)


def test_docx_builds() -> None:
    pytest.importorskip("docx")
    from render import sean_docx

    plan = json.loads((FIXTURES / f"{TRACE}.plan.json").read_text(encoding="utf-8"))
    doc = sean_docx.build(plan, DB if DB.exists() else None)
    assert len(doc.tables) == 3
    assert len(doc.tables[1].rows) == 1 + len(plan["activities"])
