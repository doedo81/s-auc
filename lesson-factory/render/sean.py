"""LessonPlan JSON → 세안(교수·학습 과정안) 조판 데이터.

여기서는 문자열까지만 만든다. `.docx` 로 굽는 일은 sean_docx.py 가 한다.
둘을 나눈 이유는 표기 규약을 의존성 없이 테스트하기 위해서다 —
python-docx 를 깔지 않아도 "T/S 표기가 맞는가"를 확인할 수 있어야 한다.

표기 규약은 실물 `사회_2-1_1차시_세안.docx` 에서 그대로 가져왔다.

    발화        `T ` / `S ` (콜론 없음), 학생 발화는 큰따옴표
    활동 덩어리 `▶ 제목`
    절차        `① … → ② … → ③ …`
    시간        프라임 기호 `5′`
    자료·유의점 `★자료` / `※유의점` 을 한 칸에 함께
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"


def _circled(i: int) -> str:
    return CIRCLED[i] if i < len(CIRCLED) else f"({i + 1})"


def _pages(pair: list[int] | None, suffix: str = "쪽") -> str:
    if not pair:
        return ""
    if len(pair) == 1 or pair[0] == pair[-1]:
        return f"{pair[0]}{suffix}"
    return f"{pair[0]}~{pair[-1]}{suffix}"


# ------------------------------------------------------------------ 머리표

def standard_lines(plan: dict, db_path: Path | None = None) -> list[str]:
    """성취기준을 '[코드] 문구' 형태로. 문구는 DB 조회로만 가져온다.

    CLAUDE.md B-1: 조회에 실패하면 지어내지 않는다. 코드만 인쇄한다.
    """
    lines = []
    conn = sqlite3.connect(db_path) if db_path and Path(db_path).exists() else None
    try:
        for code in plan["standards"]:
            text = None
            if conn is not None:
                row = conn.execute("SELECT text FROM standards WHERE code = ?", (code,)).fetchone()
                text = row[0] if row else None
            lines.append(f"[{code}] {text}" if text else f"[{code}]")
    finally:
        if conn is not None:
            conn.close()
    return lines


def header_pairs(plan: dict, db_path: Path | None = None) -> list[tuple[str, str, str, str]]:
    """머리표 5행. 각 행은 (라벨, 값, 라벨, 값)."""
    meta = plan["meta"]

    unit = meta["unit"]
    if meta.get("sub_unit"):
        unit = f"{unit} ({meta['sub_unit']})"

    period = f"{meta['period']}차시"
    if meta.get("sub_unit_period"):
        period = f"{period} (소단원 {meta['sub_unit_period']})"

    textbook = _pages(meta.get("textbook_pages"))
    if meta.get("teacher_guide_pages"):
        textbook = f"{textbook} (지도서 {_pages(meta['teacher_guide_pages'])})".strip()

    objectives = " / ".join(o["text"] for o in plan["objectives"])

    return [
        ("단원", unit, "차시", period),
        ("본시 주제", meta.get("lesson_title") or "", "교과서", textbook),
        ("성취기준", "\n".join(standard_lines(plan, db_path)),
         "대상/일시", f"{meta['grade']}학년    반 (    명) /      년    월    일    교시"),
        ("학습 목표", objectives, "수업 모형", plan.get("teaching_model") or ""),
        ("사회적 기술", plan["social_skill"], "학습 자료", " · ".join(all_materials(plan))),
    ]


def all_materials(plan: dict) -> list[str]:
    """머리표 '학습 자료' — 활동별 ★ 와 게임 준비물을 합쳐 중복을 없앤다.

    슬라이드 번호(`슬라이드 5~7`)는 차시 전체로 보면 한 벌이므로 '수업 슬라이드' 하나로 접는다.
    쪽수도 같은 이유로 뗀다 — 떼지 않으면 `교과서 76쪽 · 교과서 77~78쪽 · 교과서 78쪽` 처럼
    같은 물건이 세 번 실린다. 쪽수는 머리표의 '교과서' 칸과 활동별 ★ 에 이미 있다.
    """
    seen: list[str] = []
    slides = False
    for a in plan["activities"]:
        items = list(a.get("materials", []))
        items += (a.get("game") or {}).get("materials", [])
        for m in items:
            if m.startswith("슬라이드"):
                slides = True
                continue
            m = re.sub(r"\s*[0-9]+(~[0-9]+)?쪽$", "", m).strip()
            if m and m not in seen:
                seen.append(m)
    return (["수업 슬라이드"] if slides else []) + seen


# --------------------------------------------------------------- 본시 과정 표

def activity_cell(activity: dict) -> str:
    """셋째 열 '교수·학습 활동 (T/S)' 한 칸."""
    out: list[str] = []
    for block in activity.get("blocks", []):
        out.append(f"▶ {block['title']}")
        procedure = block.get("procedure") or []
        if procedure:
            out.append(" → ".join(f"{_circled(i)} {step}" for i, step in enumerate(procedure)))
        for line in block.get("lines", []):
            speaker = line["speaker"]
            out.append(line["text"] if speaker == "—" else f"{speaker} {line['text']}")
    return "\n".join(out)


def materials_cell(activity: dict) -> str:
    """다섯째 열 '자료(★)·유의점(※)' 한 칸.

    표기 기호는 렌더러가 붙인다. 데이터가 이미 `★`·`※` 를 달고 오면 `※★ …` 처럼 두 번
    찍히므로 앞머리에서 떼어 낸다 — 기호의 출처는 여기 한 곳뿐이어야 한다.
    """
    out = [f"★{_unmark(m)}" for m in activity.get("materials", [])]
    out += [f"※{_unmark(c)}" for c in activity.get("cautions", [])]
    return "\n".join(out)


def _unmark(text: str) -> str:
    return re.sub(r"^[★※\s]+", "", text).strip()


def process_rows(plan: dict) -> list[tuple[str, str, str, str, str]]:
    """본시 교수·학습 과정 표. 각 행은 5열."""
    rows = []
    for a in plan["activities"]:
        rows.append((
            a.get("stage_label") or a["phase"],
            "\n".join(a.get("learning_content") or []),
            activity_cell(a),
            f"{a['minutes']}′",
            materials_cell(a),
        ))
    return rows


# ---------------------------------------------------------------- 평가 계획

def assessment_rows(plan: dict) -> list[tuple[str, str, str, str]]:
    """평가 계획 표. 각 행은 (평가 요소, 평가 기준, 방법, 시기)."""
    rows = []
    for obs in plan["assessment"].get("observations", []):
        levels = obs.get("levels") or {}
        if levels:
            order = ("상", "중", "하") if obs.get("scale") == "상중하" else ("도달", "부분도달", "지원필요")
            parts = []
            for name in order:
                if name not in levels:
                    continue
                text = f"{name} {levels[name]}"
                if name in ("하", "지원필요") and levels.get("하_support"):
                    text = f"{text} → {levels['하_support']}"
                parts.append(text)
            criterion = "\n".join(parts)
        else:
            criterion = obs.get("criterion") or ""
        rows.append((obs.get("element") or "", criterion, obs.get("method") or "", obs["moment"]))
    return rows


# ---------------------------------------------------------------- 판서 계획
#
# 파생 뷰다. 별도 입력을 받지 않는다 — 본문과 어긋날 수 없게 하려는 것이다.

def board_plan(plan: dict) -> list[str]:
    meta = plan["meta"]
    unit_no = meta["unit"].split(".")[0].strip()
    unit_name = meta["unit"].split(".", 1)[-1].strip()
    period_no = meta["period"].split("/")[0]

    title = f"[{unit_no}단원] {unit_name} — {period_no}차시"
    if meta.get("lesson_title"):
        title = f"{title} {meta['lesson_title'].split('—')[0].strip()}"

    lines = [title]

    if plan.get("learning_problem"):
        lines.append(f"◦ 공부할 문제: {plan['learning_problem']}")

    steps = []
    for a in plan["activities"]:
        if a["phase"] != "전개":
            continue
        label = (a.get("stage_label") or "").replace("전개 ", "") or a["id"]
        name = (a.get("game") or {}).get("name")
        if not name:
            blocks = a.get("blocks") or []
            name = blocks[-1]["title"].split("—")[-1].strip() if blocks else ""
        structure = a.get("kagan_structure")
        steps.append(f"{label} {name}({structure})" if structure else f"{label} {name}")
    if steps:
        lines.append("◦ " + " → ".join(steps))

    closing = []
    if plan.get("closing_sentence"):
        closing.append(f"오늘의 한 문장 “{plan['closing_sentence']['answer']}”")
    for a in plan["activities"]:
        if a["phase"] == "정리" and a.get("game"):
            closing.append(a["game"]["name"])
    if closing:
        lines.append("◦ 정리: " + " + ".join(closing))

    return lines


# ------------------------------------------------------------------ 전체 조립

def render_markdown(plan: dict, db_path: Path | None = None) -> str:
    """세안 전문을 텍스트로. 구조 확인·왕복 테스트용이며, 배부용은 sean_docx.py 가 만든다."""
    meta = plan["meta"]
    out: list[str] = [
        f"{meta['subject']}과 교수·학습 과정안 (세안)",
        "",
        f"{meta['grade']}학년 {meta['semester']}학기 · {meta['unit'].split('.')[0].strip()}단원 "
        f"{meta.get('sub_unit', '').split()[0]} · {meta['period'].split('/')[0]}차시"
        f" | {plan.get('teaching_model', '')}".rstrip(" |"),
        "",
    ]

    for label_a, value_a, label_b, value_b in header_pairs(plan, db_path):
        out.append(f"| {label_a} | {value_a} | {label_b} | {value_b} |".replace("\n", " "))
    out.append("")

    out.append("■ 본시 교수·학습 과정")
    out.append("")
    out.append("| 단계(분) | 학습 내용 | 교수·학습 활동 (T 교사 / S 학생 예상 반응) | 시간 | 자료(★)·유의점(※) |")
    for row in process_rows(plan):
        out.append("| " + " | ".join(c.replace("\n", "  ") for c in row) + " |")
    out.append("")

    rows = assessment_rows(plan)
    if rows:
        out.append("■ 평가 계획")
        out.append("")
        out.append("| 평가 요소 | 평가 기준 | 방법 | 시기 |")
        for row in rows:
            out.append("| " + " | ".join(c.replace("\n", "  ") for c in row) + " |")
        out.append("")

    out.append("■ 판서 계획")
    out.append("")
    out.extend(board_plan(plan))
    out.append("")

    if plan.get("guidance_notes"):
        out.append("■ 지도상의 유의점")
        out.append("")
        for i, note in enumerate(plan["guidance_notes"]):
            out.append(f"{_circled(i)} {note}")
        out.append("")

    out.append(plan["copyright_notice"])
    return "\n".join(out)
