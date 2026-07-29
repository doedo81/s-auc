"""활동지 렌더러 — 학생용에 정답이 실리지 않는가.

CLAUDE.md D-7: *"활동지에 정답을 인쇄하지 않는다 — 정답은 교사용에만."*
이 파일의 절반은 그 한 줄을 지키는 시험이다. 나머지 절반은 골격(🎯 학습 목표가 맨 위,
📖 교과서 쪽, 💡·⭐, 📝 마무리)이 매 차시 같은지를 본다.

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

from checks import cross_checks, has_errors  # noqa: E402
from render import worksheet as layout  # noqa: E402

CONTRACTS = ROOT / "contracts"
FIXTURES = ROOT / "tests" / "fixtures"
TRACES = ("사회-5-2-2단원-1차시", "사회-5-2-2단원-2차시")


def load(trace: str) -> dict:
    return json.loads((FIXTURES / f"{trace}.worksheet.json").read_text(encoding="utf-8"))


@pytest.fixture
def sheet() -> dict:
    return load("사회-5-2-2단원-2차시")


# ------------------------------------------------------------- 정답이 새지 않는가

def test_student_sheet_has_no_examples(sheet: dict) -> None:
    """`example` 은 교사용이다. 학생용 조판은 그 자리를 만들지 않는다."""
    student = layout.render_markdown(sheet, teacher=False)
    for item in sheet["items"]:
        assert item["example"] not in student
    assert "예시 답안" not in student


def test_student_sheet_has_no_teacher_notes(sheet: dict) -> None:
    student = layout.render_markdown(sheet, teacher=False)
    for note in sheet["teacher_notes"]:
        assert note not in student
    assert "OX 정답" not in student


def test_teacher_sheet_has_both(sheet: dict) -> None:
    """반대로 교사용에는 다 있어야 한다 — 없으면 교사가 판정할 수 없다."""
    teacher = layout.render_markdown(sheet, teacher=True)
    assert "OX 정답은 O·O·X" in teacher
    assert "어짊" in teacher


def test_ox_answers_never_printed(sheet: dict) -> None:
    """OX 는 문제만 나가고 (   ) 빈칸으로 끝난다."""
    lines = layout.closing_lines(sheet)
    ox = [ln for ln in lines if ln.strip().startswith(("①", "②", "③", "④"))]
    assert len(ox) == 4
    assert all(ln.endswith("(   )") for ln in ox)


def test_row_labels_are_questions_not_answers(sheet: dict) -> None:
    """표 첫 칸에 미리 박아 두는 것은 **문제**여야 한다.

    건물 이름을 인쇄해 두면 옮겨 적는 시간이 준다. 같은 자리에 덕목을 인쇄하면
    활동이 통째로 사라진다 — 렌더러가 이 필드를 쓰기 시작하면서 생긴 위험이다.
    """
    item = next(i for i in sheet["items"] if i["id"] == "BUILDING_VIRTUE")
    assert item["row_labels"] == ["흥인지문", "돈의문", "숭례문", "보신각"]
    for virtue in ("인", "의", "예", "신", "어짊", "의로움"):
        assert virtue not in item["columns"]


def test_answer_in_row_labels_is_detected(sheet: dict) -> None:
    """검사가 실제로 잡는지 — 정답을 표 첫 칸에 넣어 본다."""
    plan = json.loads((FIXTURES / "사회-5-2-2단원-2차시.plan.json").read_text(encoding="utf-8"))
    leaky = copy.deepcopy(sheet)
    item = next(i for i in leaky["items"] if i["id"] == "BUILDING_VIRTUE")
    item["row_labels"] = ["흥인지문 인(어짊)", "돈의문 의(의로움)", "숭례문 예(예의 바름)", "보신각 신(믿음)"]
    problems = cross_checks.check_game_answer_hidden(plan, leaky)
    assert has_errors(problems), "표 첫 칸으로 샌 정답을 못 잡았다"


# ------------------------------------------------------------- 골격은 매 차시 같다

@pytest.mark.parametrize("trace", TRACES)
def test_skeleton_is_the_same_every_lesson(trace: str) -> None:
    sheet = load(trace)
    head = layout.head_lines(sheet)
    assert head[0].startswith("🎯")
    assert "📖 먼저 교과서" in head[1] and "🤝 협동학습" in head[1]
    assert "이름" in head[-1]

    hint = layout.hint_line(sheet)
    assert hint and hint.startswith("💡") and "⭐" in hint

    closing = layout.closing_lines(sheet)
    assert closing[0] == "📝 오늘의 한 문장"
    assert any("OX 4문제" in ln for ln in closing)


@pytest.mark.parametrize("trace", TRACES)
def test_every_item_gets_a_drawable_answer_space(trace: str) -> None:
    """`answer_space` 값마다 그릴 수 있는 치수가 나와야 한다."""
    for item in load(trace)["items"]:
        kind, spec = layout.answer_space(item)
        assert kind in ("줄", "표", "네모칸")
        if kind == "줄":
            assert spec["count"] >= 1
        elif kind == "표":
            assert len(spec["columns"]) >= 2 and spec["rows"] >= 1


def test_table_without_columns_falls_back_instead_of_guessing() -> None:
    """열 규격이 없으면 몇 칸짜리인지 알 수 없다. 지어내지 않고 빈 칸으로 떨어뜨린다."""
    kind, spec = layout.answer_space({"answer_space": "표", "id": "X", "prompt": "p"})
    assert kind == "네모칸"
    assert "columns" in spec["note"]


def test_activity_sections_group_two_items_of_one_activity(sheet: dict) -> None:
    """짝 점검은 한 활동에 칸이 둘이다 (문제세트 + 짝점검). 활동 제목은 하나만 붙는다."""
    sections = layout.activity_sections(sheet)
    assert len(sections) == 2
    assert [len(s["items"]) for s in sections] == [2, 1]
    assert sections[0]["title"].startswith("활동 1 · ‘나는 한양 도성 설계자’")


# ------------------------------------------------------------- 스키마 · 워드

@pytest.mark.parametrize("trace", TRACES)
def test_worksheet_matches_schema(trace: str) -> None:
    schema = json.loads((CONTRACTS / "worksheet.schema.json").read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(schema).iter_errors(load(trace)))


@pytest.mark.parametrize("trace", TRACES)
def test_docx_builds_both_versions(trace: str) -> None:
    pytest.importorskip("docx")
    from render import worksheet_docx

    sheet = load(trace)
    student = worksheet_docx.build(sheet, teacher=False)
    teacher = worksheet_docx.build(sheet, teacher=True)

    student_text = "\n".join(p.text for p in student.paragraphs)
    teacher_text = "\n".join(p.text for p in teacher.paragraphs)
    assert sheet["footer"] in student_text
    for note in sheet["teacher_notes"]:
        assert note not in student_text
        assert note in teacher_text
