"""활동지 조판 데이터 — 종이 한 장의 순서와 문구를 여기서 정한다.

`sean.py` 와 같은 역할이다. 워드를 모르는 순수 함수만 두고, 표 그리기는
`worksheet_docx.py` 가 한다. 그래야 조판 규칙을 시험할 수 있다.

**학생용과 교사용을 나눈다.** CLAUDE.md D-7: *"활동지에 정답을 인쇄하지 않는다 —
정답은 교사용에만."* 같은 JSON 에서 두 벌이 나오고, 학생용에는 `example` ·
`teacher_notes` · OX 정답이 **구조적으로** 실리지 않는다. 지우는 게 아니라 애초에
학생용 조판 함수가 그 자리를 만들지 않는다.

골격은 매 차시 같다 (CLAUDE.md D-7).

    🎯 학습 목표  →  📖 교과서 쪽 · 🤝 협동학습 · 사회적 기술  →  이름칸
    →  활동칸들  →  💡 느린 힌트 · ⭐ 빠른 보너스  →  📝 마무리(한 문장 + OX 4)
"""

from __future__ import annotations

NAME_LINE = "5학년 5반 ______모둠 ______번   이름 ____________"

# 활동칸 하나를 어떻게 그릴지. (종류, 데이터) 로 렌더러에 넘긴다.
#   ("줄",   {"count": 4})
#   ("표",   {"columns": [...], "rows": 4, "labels": [...]})
#   ("네모칸", {"height_cm": 3.5})


def head_lines(worksheet: dict) -> list[str]:
    """머리 세 줄. 학습 목표가 맨 위에 크게 온다."""
    out = [f"🎯 {worksheet['objective']}"] if worksheet.get("objective") else []

    second: list[str] = []
    if worksheet.get("textbook_pages"):
        pages = worksheet["textbook_pages"]
        span = f"{pages[0]}~{pages[-1]}" if len(pages) > 1 and pages[0] != pages[-1] else f"{pages[0]}"
        second.append(f"📖 먼저 교과서 {span}쪽을 펴요")
    if worksheet.get("structure_label"):
        second.append(f"🤝 협동학습 {worksheet['structure_label']}")
    if worksheet.get("social_skill"):
        second.append(f"사회적 기술 · {worksheet['social_skill']}")
    if second:
        out.append("   ".join(second))

    out.append(NAME_LINE)
    return out


def answer_space(item: dict) -> tuple[str, dict]:
    """항목의 답 칸을 (종류, 치수) 로 옮긴다.

    `표`·`격자` 에 `columns` 가 없으면 그릴 수 없다 — 몇 칸짜리인지 모르기 때문이다.
    지어내지 않고 네모칸으로 떨어뜨린 뒤 렌더러가 표시하게 둔다.
    """
    kind = item["answer_space"]
    labels = item.get("row_labels") or []
    rows = item.get("rows") or len(labels) or 4

    if kind == "줄":
        return "줄", {"count": item.get("lines", 3)}

    if kind in ("표", "격자"):
        columns = item.get("columns")
        if not columns:
            return "네모칸", {"height_cm": 4.0, "note": "표 규격(columns)이 없어 빈 칸으로 그렸다"}
        return "표", {"columns": columns, "rows": rows, "labels": labels}

    if kind == "체크박스":
        return "표", {"columns": ["", "✔", "칭찬 한마디"], "rows": rows, "labels": labels, "compact": True}

    if kind == "선긋기":
        return "표", {"columns": ["", ""], "rows": rows, "labels": labels}

    return "네모칸", {"height_cm": 3.5}


def activity_sections(worksheet: dict) -> list[dict]:
    """활동칸을 `for_activity` 별로 묶는다.

    한 활동에 칸이 둘일 수 있다(짝 점검은 문제세트 + 짝점검 두 칸을 요구한다).
    제목은 `activity_titles` 를 순서대로 붙인다 — 개수가 모자라면 붙이지 않는다.
    """
    order: list[str] = []
    grouped: dict[str, list[dict]] = {}
    for item in worksheet["items"]:
        key = item["for_activity"]
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(item)

    titles = worksheet.get("activity_titles") or []
    sections = []
    for i, key in enumerate(order):
        sections.append({
            "activity": key,
            "title": f"활동 {i + 1} · {titles[i]}" if i < len(titles) else f"활동 {i + 1}",
            "items": grouped[key],
        })
    return sections


def hint_line(worksheet: dict) -> str | None:
    hints = worksheet.get("hints") or {}
    parts = []
    if hints.get("slow"):
        parts.append(f"💡 {hints['slow']}")
    if hints.get("fast"):
        parts.append(f"⭐ {hints['fast']}")
    return "      ".join(parts) or None


def closing_lines(worksheet: dict) -> list[str]:
    """📝 마무리. **정답은 절대 여기 오지 않는다** — 스키마가 문자열 배열이라 담을 자리도 없다."""
    closing = worksheet.get("closing")
    if not closing:
        return []
    out = ["📝 오늘의 한 문장", f"   {closing['sentence_prompt']}", "", "📝 OX 4문제 (다 맞혀야 통과!)"]
    for i, statement in enumerate(closing["ox_statements"]):
        out.append(f"   {_circled(i)} {statement}   (   )")
    out += ["", f"   {closing['result_line']}"]
    return out


def teacher_lines(worksheet: dict) -> list[str]:
    """교사용에만 붙는 뒷장. 학생용 조판에서는 이 함수가 호출되지 않는다."""
    out: list[str] = []
    if worksheet.get("teacher_notes"):
        out.append("■ 교사용 안내")
        out += [f"{_circled(i)} {n}" for i, n in enumerate(worksheet["teacher_notes"])]
    examples = [(i["id"], i["example"]) for i in worksheet["items"] if i.get("example")]
    if examples:
        out += ["", "■ 예시 답안 (학생용에는 인쇄되지 않는다)"]
        out += [f"· {name} — {text}" for name, text in examples]
    return out


def _circled(index: int) -> str:
    return "①②③④⑤⑥⑦⑧⑨⑩"[index] if index < 10 else f"({index + 1})"


def render_markdown(worksheet: dict, *, teacher: bool = False) -> str:
    """dry_run 미리보기. 워드 없이 눈으로 확인하는 용도."""
    out = [f"# {worksheet['title']}", ""]
    out += head_lines(worksheet)
    for section in activity_sections(worksheet):
        out += ["", f"## {section['title']}"]
        for item in section["items"]:
            kind, spec = answer_space(item)
            out.append(f"- {item['prompt']}")
            out.append(f"  [{kind} {spec}]")
    hint = hint_line(worksheet)
    if hint:
        out += ["", hint]
    closing = closing_lines(worksheet)
    if closing:
        out += [""] + closing
    if teacher:
        lines = teacher_lines(worksheet)
        if lines:
            out += ["", "---", ""] + lines
    out += ["", worksheet["footer"]]
    return "\n".join(out)
