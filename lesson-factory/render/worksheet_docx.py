"""Worksheet JSON → 활동지 `.docx`. 학생용 한 벌, 교사용 한 벌.

조판 데이터는 `worksheet.py` 가 만든다. 이 파일은 워드 표에 앉히는 일만 한다.

**학생용에는 정답이 구조적으로 들어가지 않는다** (CLAUDE.md D-7). `example` 과
`teacher_notes` 는 `--teacher` 를 줬을 때만 조판되며, 학생용 경로에서는 그 함수를
아예 부르지 않는다. 지우고 남은 것이 아니라 처음부터 없는 것이다.

CLAUDE.md B-2: 파일 쓰기는 dry_run 이 기본이다.

    python3 -m render.worksheet_docx tests/fixtures/사회-5-2-2단원-2차시.worksheet.json
    python3 -m render.worksheet_docx tests/fixtures/사회-5-2-2단원-2차시.worksheet.json --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core import paths

from . import worksheet as layout

ROOT = Path(__file__).resolve().parent.parent


def _para(doc, text: str, *, size: int = 10, bold: bool = False, space_after: int = 2):
    from docx.shared import Pt

    para = doc.add_paragraph()
    para.paragraph_format.space_after = Pt(space_after)
    run = para.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = "맑은 고딕"
    return para


def _cell(cell, text: str, *, bold: bool = False, size: int = 9) -> None:
    from docx.shared import Pt

    cell.text = ""
    para = cell.paragraphs[0]
    run = para.add_run(text)
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = "맑은 고딕"


def _draw_answer_space(doc, kind: str, spec: dict) -> None:
    from docx.shared import Cm, Pt

    if kind == "줄":
        for _ in range(spec["count"]):
            para = doc.add_paragraph()
            para.paragraph_format.space_after = Pt(6)
            run = para.add_run("_" * 92)
            run.font.size = Pt(9)
        return

    if kind == "표":
        columns = spec["columns"]
        labels = spec.get("labels") or []
        rows = spec.get("rows") or len(labels) or 4
        table = doc.add_table(rows=rows + 1, cols=len(columns))
        table.style = "Table Grid"
        for cell, text in zip(table.rows[0].cells, columns):
            _cell(cell, text, bold=True)
        for i, row in enumerate(table.rows[1:]):
            if i < len(labels):
                _cell(row.cells[0], labels[i], bold=True)
            if spec.get("compact"):
                row.cells[1].width = Cm(1.5)
            row.height = Cm(0.9)
        return

    # 네모칸
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    table.rows[0].height = Cm(spec.get("height_cm", 3.5))
    if spec.get("note"):
        _cell(table.rows[0].cells[0], "")


def build(sheet: dict, *, teacher: bool = False):
    """python-docx Document 를 만들어 돌려준다. 파일로 쓰지 않는다."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt

    doc = Document()
    for section in doc.sections:
        section.left_margin = section.right_margin = Inches(0.6)
        section.top_margin = section.bottom_margin = Inches(0.5)

    title = _para(doc, sheet["title"] + (" [교사용]" if teacher else ""), size=13, bold=True)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    head = layout.head_lines(sheet)
    if head:
        _para(doc, head[0], size=12, bold=True)          # 🎯 학습 목표 — 맨 위에 크게
        for line in head[1:]:
            _para(doc, line, size=9)

    for section in layout.activity_sections(sheet):
        _para(doc, section["title"], size=11, bold=True, space_after=4)
        for item in section["items"]:
            _para(doc, item["prompt"], size=10)
            kind, spec = layout.answer_space(item)
            _draw_answer_space(doc, kind, spec)

    hint = layout.hint_line(sheet)
    if hint:
        _para(doc, hint, size=9)

    closing = layout.closing_lines(sheet)
    if closing:
        _para(doc, "", size=6)
        for line in closing:
            _para(doc, line, size=10, bold=line.startswith("📝"), space_after=1)

    if teacher:
        lines = layout.teacher_lines(sheet)
        if lines:
            doc.add_page_break()
            for line in lines:
                _para(doc, line, size=10, bold=line.startswith("■"))

    footer = _para(doc, sheet["footer"], size=8)
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Worksheet JSON → 활동지 .docx (학생용·교사용)")
    ap.add_argument("worksheet", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None, help="산출물 뿌리 (기본: .env 의 LESSON_OUT 또는 artifacts/)")
    ap.add_argument("--write", action="store_true", help="실제로 파일을 쓴다 (기본은 dry_run)")
    args = ap.parse_args(argv)

    sheet = json.loads(args.worksheet.read_text(encoding="utf-8"))
    folder = paths.lesson_dir(sheet["trace_id"], args.out)
    student = folder / f"{sheet['trace_id']}-활동지-v1.docx"
    teacher = folder / f"{sheet['trace_id']}-활동지-교사용-v1.docx"

    if not args.write:
        print(layout.render_markdown(sheet, teacher=True))
        print(f"\n[dry_run] 저장하려면 --write. 저장 위치:\n  {student}\n  {teacher}", file=sys.stderr)
        return 0

    folder.mkdir(parents=True, exist_ok=True)
    build(sheet, teacher=False).save(student)
    build(sheet, teacher=True).save(teacher)
    print(f"저장함: {student}")
    print(f"저장함: {teacher}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
