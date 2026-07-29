"""지도안 ↔ 활동지 ↔ 슬라이드 교차 검증.

이 프로젝트가 존재하는 이유. 실과 4단원에서 실제로 일어난 실패
("지도안 파일 부재 → 성취기준 기반 재구성 → 원본 대조 필요")를 기계가 막는다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import Problem, print_checks

CONTRACTS = Path(__file__).resolve().parent.parent / "contracts"


def _kagan_index() -> dict[str, dict]:
    data = json.loads((CONTRACTS / "kagan_structures.json").read_text(encoding="utf-8"))
    return {s["id"]: s for s in data["structures"]}


def check_worksheet_item_refs(plan: dict, worksheet: dict) -> list[Problem]:
    """지도안이 가리키는 활동지 항목이 실재하는가 — 그리고 그 역도."""
    problems = []
    declared = {i["id"] for i in worksheet["items"]}
    referenced: set[str] = set()

    for a in plan["activities"]:
        for wid in a["worksheet_items"]:
            referenced.add(wid)
            if wid not in declared:
                problems.append(
                    Problem("worksheet_refs", f"활동 {a['id']} 가 없는 활동지 항목 {wid} 를 가리킴")
                )

    for wid in sorted(declared - referenced):
        problems.append(
            Problem("worksheet_refs", f"활동지 항목 {wid} 를 쓰는 활동이 없음 — 학생이 빈칸을 만난다")
        )

    # 항목이 자기가 속한다고 주장하는 활동이 실재하는가
    activity_ids = {a["id"] for a in plan["activities"]}
    for item in worksheet["items"]:
        if item["for_activity"] not in activity_ids:
            problems.append(
                Problem("worksheet_refs", f"활동지 항목 {item['id']} 가 없는 활동 {item['for_activity']} 를 가리킴")
            )
    return problems


def check_kagan_roles_satisfied(plan: dict, worksheet: dict) -> list[Problem]:
    """계획한 협동 구조를 활동지가 실제로 지탱하는가. ★ 드리프트 검출의 핵심.

    예: `생각-쓰기-짝-비교` 를 골라 놓고 활동지에 개인쓰기 칸이 없으면
    비교할 산출물이 없어 구조가 성립하지 않는다. 이름만 붙은 협동을 잡아낸다.

    같은 구조를 쓰는 활동이 여러 개면 그 활동들의 칸을 합쳐서 본다.
    실물에서 하나의 구조가 여러 활동에 걸쳐 실행되기 때문이다
    (예: 모둠 합의는 앞 활동에서, 호명 발표는 뒤 활동에서).

    worksheet_verifiable=false 인 구조는 활동지가 자유 형식이라 요구 칸이 정해져 있지 않으므로
    건너뛴다. (그 사각지대는 plan_checks.check_templated_structure_has_worksheet 가 경고로 남긴다)
    """
    problems = []
    kagan = _kagan_index()
    roles_by_activity: dict[str, set[str]] = {}
    for item in worksheet["items"]:
        roles_by_activity.setdefault(item["for_activity"], set()).add(item["role"])

    by_structure: dict[str, list[str]] = {}
    for a in plan["activities"]:
        structure = a.get("kagan_structure")
        if not structure:
            continue
        if structure not in kagan:
            problems.append(Problem("kagan_roles", f"활동 {a['id']}: 모르는 구조 '{structure}'"))
            continue
        by_structure.setdefault(structure, []).append(a["id"])

    for structure, activity_ids in by_structure.items():
        spec = kagan[structure]
        if not spec.get("worksheet_verifiable"):
            continue

        have: set[str] = set()
        for aid in activity_ids:
            have |= roles_by_activity.get(aid, set())

        missing = [r for r in spec["required_item_roles"] if r not in have]
        if missing:
            where = "·".join(activity_ids)
            problems.append(
                Problem(
                    "kagan_roles",
                    f"활동 {where} 는 '{structure}' 인데 활동지에 {missing} 칸이 없음 — "
                    f"{spec.get('why', '구조가 성립하지 않는다')}",
                )
            )
    return problems


def check_activity_slide_coverage(plan: dict, deck: dict) -> list[Problem]:
    """모든 활동을 최소 1장의 슬라이드가 다루는가."""
    problems = []
    covered = {s["covers_activity"] for s in deck["slides"] if s.get("covers_activity")}
    activity_ids = {a["id"] for a in plan["activities"]}

    for aid in sorted(activity_ids - covered):
        problems.append(Problem("slide_coverage", f"활동 {aid} 를 다루는 슬라이드가 없음"))
    for aid in sorted(covered - activity_ids):
        problems.append(Problem("slide_coverage", f"슬라이드가 없는 활동 {aid} 를 가리킴"))
    return problems


def check_answer_separation(deck: dict) -> list[Problem]:
    """문제 슬라이드에 정답이 미리 노출되지 않는가.

    실물 저작 규칙("정답 선노출 금지")을 코드로 옮긴 것.
    """
    problems = []
    by_index = {s["index"]: s for s in deck["slides"]}

    for s in deck["slides"]:
        if s.get("role") != "정답":
            continue
        target = s.get("answer_of")
        if target is None:
            continue
        q = by_index.get(target)
        if q is None:
            problems.append(Problem("answer_separation", f"슬라이드 {s['index']}: 문제 {target} 가 없음"))
            continue
        if q.get("role") != "문제":
            problems.append(
                Problem("answer_separation", f"슬라이드 {s['index']} 의 answer_of={target} 가 문제 슬라이드가 아님")
            )
        # 정답 문구가 문제 화면 본문에 이미 있으면 선노출이다
        q_body = " ".join(q.get("body", []))
        for line in s.get("body", []):
            if line.strip() and line.strip() in q_body:
                problems.append(
                    Problem("answer_separation", f"정답 '{line.strip()}' 이 문제 슬라이드 {target} 본문에 이미 노출됨")
                )

    for s in deck["slides"]:
        if s.get("role") != "OX":
            continue
        body = " ".join(s.get("body", []))
        for ox in s.get("ox_items", []):
            if ox["answer"] in body.split() or ox["rationale"] in body:
                problems.append(
                    Problem("answer_separation", f"슬라이드 {s['index']}: OX 정답·근거가 화면 본문에 노출됨")
                )
    return problems


def check_palette(plan: dict, deck: dict) -> list[Problem]:
    """슬라이드 팔레트가 시대에 맞는가."""
    palettes = json.loads((CONTRACTS / "era_palettes.json").read_text(encoding="utf-8"))["eras"]
    problems = []

    if deck["era"] != plan["era"]:
        problems.append(Problem("palette", f"덱의 시대 '{deck['era']}' ≠ 지도안의 '{plan['era']}'"))
        return problems

    spec = palettes.get(deck["era"])
    if spec is None or not spec.get("confirmed") or spec.get("background") is None:
        return []

    got = deck.get("palette") or {}
    severity = "error" if spec["confirmed"] else "warn"
    for field in ("background", "accent"):
        if got.get(field) != spec[field]:
            problems.append(
                Problem(
                    "palette",
                    f"{deck['era']}({spec['palette_name']}) {field} 는 {spec[field]} 여야 하는데 {got.get(field)}",
                    severity=severity,
                )
            )
    return problems


# 활동지에 정답이 새어 나온 흔적. 제작 규칙 §4: "활동지에는 정답(O/X)을 표시하지 않는다 — 문제만!"
#
# 약안 ④ 의 표기를 그대로 흡수한다 — '(O)' 뿐 아니라 '(X — 한양)' '(O·추론)' 처럼
# 괄호 안에 설명이 붙는 형태가 실물에 있다. 그걸 복사해 오는 것이 가장 흔한 사고다.
_ANSWER_PATTERN = re.compile(r"\(\s*[OX]\s*[)·\-—,]")
_ANSWER_WORDS = ("정답:", "답:")


def check_worksheet_answers_hidden(worksheet: dict) -> list[Problem]:
    """활동지에 정답이 인쇄돼 있지 않은가.

    제작 규칙 §4 가 못박은 것이라 실패로 다룬다 — 학생용 인쇄본에 정답이 있으면
    OX 4문제가 성립하지 않는다. 스키마가 ox_statements 를 문자열 배열로 둬서
    정답을 담을 자리를 아예 없앴지만, 문장 안에 '(O)' 를 적어 넣는 것까지는 못 막는다.

    example 은 교사용이므로 검사하지 않는다.
    """
    problems = []
    closing = worksheet.get("closing")
    if closing:
        for i, statement in enumerate(closing["ox_statements"], 1):
            found = _ANSWER_PATTERN.search(statement)
            if found:
                problems.append(
                    Problem("worksheet_answers", f"OX {i}번 문장에 정답 표시 '{found.group()}' 가 들어 있음")
                )
            for word in _ANSWER_WORDS:
                if word in statement:
                    problems.append(
                        Problem("worksheet_answers", f"OX {i}번 문장에 '{word}' 가 들어 있음")
                    )

    for item in worksheet["items"]:
        for where, text in _printed_item_text(item):
            for mark in _ANSWER_WORDS:
                if mark in text:
                    problems.append(
                        Problem("worksheet_answers", f"활동지 항목 {item['id']} {where}에 '{mark}' 가 들어 있음")
                    )
    return problems


def _printed_item_text(item: dict) -> list[tuple[str, str]]:
    """항목에서 **학생 종이에 실제로 인쇄되는** 글자만 모은다.

    `row_labels`·`columns` 를 렌더러가 쓰기 시작하면서(2026-07-29) 정답이 샐 자리가
    늘었다. 표 첫 칸에 건물 이름을 미리 박아 두는 것은 시간을 아끼는 좋은 일이지만,
    같은 자리에 덕목을 박으면 활동이 통째로 사라진다. `example` 은 교사용이라 뺀다.
    """
    out = [("발문", item["prompt"])]
    out += [("표 머리", c) for c in item.get("columns") or []]
    out += [("표 첫 칸", label) for label in item.get("row_labels") or []]
    return out


def check_game_answer_hidden(plan: dict, worksheet: dict) -> list[Problem]:
    """게임 정답이 학생 활동지에 인쇄되지 않았는가.

    `game.answer` 는 교사용이다. 정답을 지도안에 적어 두는 것과 활동지에 인쇄하는 것은
    전혀 다른 일인데, 활동지를 지도안에서 파생시키다 보면 그대로 흘러 들어가기 쉽다.
    OX 정답에 이미 같은 규칙이 있고(제작 규칙 §4), 게임 정답이라고 다를 이유가 없다.

    발문·문장틀·활동 제목만 본다. teacher_notes 와 example 은 학생용 인쇄본에
    나가지 않으므로 검사하지 않는다.
    """
    answers = [
        (a["id"], a["game"]["answer"])
        for a in plan["activities"]
        if a.get("game") and a["game"].get("answer")
    ]
    if not answers:
        return []

    student_text = [
        *(text for i in worksheet["items"] for _, text in _printed_item_text(i)),
        *(worksheet.get("activity_titles") or []),
        *((worksheet.get("hints") or {}).get(k, "") for k in ("slow", "fast")),
    ]
    closing = worksheet.get("closing")
    if closing:
        student_text.append(closing["sentence_prompt"])
        student_text.extend(closing["ox_statements"])

    problems = []
    for aid, answer in answers:
        for fragment in _answer_fragments(answer):
            leaked = next((t for t in student_text if fragment in t), None)
            if leaked is not None:
                problems.append(
                    Problem(
                        "game_answer",
                        f"활동 {aid} 게임 정답 '{fragment}' 이 학생 활동지에 인쇄됨 — 정답은 교사용이다",
                    )
                )
                break
    return problems


def _answer_fragments(answer: str) -> list[str]:
    """정답 한 줄을 조각으로 나눈다.

    정답은 보통 `흥인지문 인(어짊) · 돈의문 의(의로움) · …` 처럼 한 줄에 여럿이 들어간다.
    통째로만 대조하면 한 조각만 활동지로 새어 나갔을 때 놓친다 — 그리고 실제로 새는
    쪽은 언제나 한 조각이다.
    """
    parts = [p.strip() for p in re.split(r"\s*·\s*", answer) if p.strip()]
    return parts if len(parts) > 1 else [answer]


def _normalize_text(s: str) -> str:
    """구두점·공백 차이는 드리프트가 아니다.

    실물이 실제로 이렇게 갈린다 — 세안은 '…알고, 단원 탐구 질문을' 이고
    약안·학습지는 '…알고 탐구 질문을' 이다. 쉼표만 다른 것까지 경고하면
    선생님이 도구와 쉼표 싸움을 하게 된다. 낱말이 다를 때만 걸리게 한다.
    """
    return re.sub(r"[\s.,·]", "", s)


def check_worksheet_skeleton(plan: dict, worksheet: dict) -> list[Problem]:
    """매 차시 들어가야 할 골격이 갖춰졌는가.

    제작 규칙 §3·§4 가 '매 차시' 라고 못박은 항목들이다. 다만 경고로 둔다 —
    실물 실과 자료는 이 규칙(사회 5-2 제작 규칙)을 따르지 않으므로,
    과목마다 다른 관행을 실패로 만들면 파이프라인이 과목을 못 넘는다.

    골격이 있으면 지도안과 어긋나는지까지 본다. 학습 목표가 두 문서에서 다르면
    학생이 보는 목표와 교사가 재는 목표가 갈린다.
    """
    problems = []

    if not worksheet.get("objective"):
        problems.append(Problem("worksheet_skeleton", "🎯 학습 목표가 활동지 맨 위에 없음", severity="warn"))
    else:
        declared = {_normalize_text(o["text"]) for o in plan["objectives"]}
        if _normalize_text(worksheet["objective"]) not in declared:
            problems.append(
                Problem(
                    "worksheet_skeleton",
                    f"학습 목표 문구가 다름 — 활동지 “{worksheet['objective']}” / "
                    f"지도안 “{' / '.join(o['text'] for o in plan['objectives'])}”",
                    severity="warn",
                )
            )

    want_pages = plan["meta"].get("textbook_pages")
    got_pages = worksheet.get("textbook_pages")
    if not got_pages:
        problems.append(Problem("worksheet_skeleton", "📖 교과서 쪽 안내가 없음", severity="warn"))
    elif want_pages and got_pages != want_pages:
        problems.append(
            Problem("worksheet_skeleton", f"활동지 교과서 쪽 {got_pages} ≠ 지도안 {want_pages}")
        )

    if worksheet.get("social_skill") and worksheet["social_skill"] not in plan["social_skill"]:
        problems.append(
            Problem("worksheet_skeleton", f"활동지 사회적 기술 '{worksheet['social_skill']}' 이 지도안과 다름")
        )

    hints = worksheet.get("hints") or {}
    if not (hints.get("slow") and hints.get("fast")):
        problems.append(
            Problem("worksheet_skeleton", "💡 느린 학습자 힌트 · ⭐ 빠른 학습자 보너스 가 갖춰지지 않음", severity="warn")
        )

    closing = worksheet.get("closing")
    if not closing:
        problems.append(
            Problem("worksheet_skeleton", "📝 마무리 루틴(한 문장 + OX 4문제)이 없음 — 사회는 기억이 중요하다", severity="warn")
        )
    elif plan.get("closing_sentence"):
        if closing["sentence_prompt"] != plan["closing_sentence"]["template"]:
            problems.append(
                Problem("worksheet_skeleton", "활동지의 '오늘의 한 문장' 빈칸이 지도안 closing_sentence 와 다름")
            )

    return problems


def run_all(plan: dict, worksheet: dict, deck: dict | None = None) -> list[Problem]:
    """덱이 없으면 지도안↔활동지 검사만 돈다.

    실물에서 활동지는 소단원 묶음 PDF 로, 슬라이드는 차시별 .pptx 로 따로 만들어져
    한쪽만 손에 있는 때가 실제로 있다. 그럴 때 검사 전체를 못 돌리게 하지 않는다.
    """
    problems = (
        check_worksheet_item_refs(plan, worksheet)
        + check_kagan_roles_satisfied(plan, worksheet)
        + check_worksheet_answers_hidden(worksheet)
        + check_game_answer_hidden(plan, worksheet)
        + check_worksheet_skeleton(plan, worksheet)
        + print_checks.run_all(plan, worksheet)
    )
    if deck is not None:
        problems += check_activity_slide_coverage(plan, deck)
        problems += check_answer_separation(deck)
        problems += check_palette(plan, deck)
    return problems
