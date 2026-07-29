"""지도안 ↔ 활동지 ↔ 슬라이드 교차 검증.

이 프로젝트가 존재하는 이유. 실과 4단원에서 실제로 일어난 실패
("지도안 파일 부재 → 성취기준 기반 재구성 → 원본 대조 필요")를 기계가 막는다.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import Problem

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

    템플릿이 없는 구조(has_template=false)는 활동지가 자유 형식이므로 건너뛴다.
    """
    problems = []
    kagan = _kagan_index()
    roles_by_activity: dict[str, set[str]] = {}
    for item in worksheet["items"]:
        roles_by_activity.setdefault(item["for_activity"], set()).add(item["role"])

    for a in plan["activities"]:
        structure = a.get("kagan_structure")
        if not structure:
            continue
        spec = kagan.get(structure)
        if spec is None:
            problems.append(Problem("kagan_roles", f"활동 {a['id']}: 모르는 구조 '{structure}'"))
            continue
        if not spec.get("has_template"):
            continue

        have = roles_by_activity.get(a["id"], set())
        missing = [r for r in spec["required_item_roles"] if r not in have]
        if missing:
            problems.append(
                Problem(
                    "kagan_roles",
                    f"활동 {a['id']} 는 '{structure}' 인데 활동지에 {missing} 칸이 없음 — "
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


def run_all(plan: dict, worksheet: dict, deck: dict) -> list[Problem]:
    return (
        check_worksheet_item_refs(plan, worksheet)
        + check_kagan_roles_satisfied(plan, worksheet)
        + check_activity_slide_coverage(plan, deck)
        + check_answer_separation(deck)
        + check_palette(plan, deck)
    )
