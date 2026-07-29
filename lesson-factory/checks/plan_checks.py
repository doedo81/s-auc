"""지도안 단독 검증 — 다른 산출물 없이 지도안만 보고 판단할 수 있는 것."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from . import Problem

CONTRACTS = Path(__file__).resolve().parent.parent / "contracts"


def check_minutes_sum(plan: dict) -> list[Problem]:
    """활동 시간 합계가 차시 길이와 같은가."""
    total = sum(a["minutes"] for a in plan["activities"])
    want = plan["meta"]["minutes"]
    if total != want:
        return [Problem("minutes_sum", f"활동 시간 합계 {total}분 ≠ 차시 {want}분")]
    return []


def check_objective_coverage(plan: dict) -> list[Problem]:
    """학습목표와 활동이 양방향으로 연결됐는가.

    교과서 활동을 대체할 수 있게 한 대신, 이 연결이 유일한 방어선이다.
    """
    problems: list[Problem] = []
    declared = {o["id"] for o in plan["objectives"]}

    used: set[str] = set()
    for a in plan["activities"]:
        for oid in a["objective_ids"]:
            used.add(oid)
            if oid not in declared:
                problems.append(
                    Problem("objective_coverage", f"활동 {a['id']} 가 없는 학습목표 {oid} 를 가리킴")
                )

    for oid in sorted(declared - used):
        problems.append(
            Problem("objective_coverage", f"학습목표 {oid} 를 다루는 활동이 하나도 없음")
        )
    return problems


def check_kagan_usage(plan: dict) -> list[Problem]:
    """전개 활동의 협동 구조 사용 — '협동적인가'를 코드로 보장하는 지점."""
    problems: list[Problem] = []
    develop = [a for a in plan["activities"] if a["phase"] == "전개"]

    if not develop:
        return [Problem("kagan_usage", "전개 활동이 하나도 없음")]

    structures = []
    for a in develop:
        s = a.get("kagan_structure")
        if not s:
            problems.append(Problem("kagan_usage", f"전개 활동 {a['id']} 에 협동 구조가 없음"))
        else:
            structures.append(s)

    if len(set(structures)) < 2 and len(develop) >= 2:
        problems.append(
            Problem(
                "kagan_usage",
                f"전개 활동 {len(develop)}개가 모두 같은 구조({structures[0] if structures else '?'}) — "
                "40분 내내 같은 형태면 학생이 지친다",
                severity="warn",
            )
        )
    return problems


def check_standards_exist(plan: dict, db_path: Path) -> list[Problem]:
    """성취기준이 DB에 실재하는가.

    CLAUDE.md B-1: 조회 실패는 작업 실패. 모델이 지어낸 코드를 차단한다.

    한계: 코드가 실재해도 수업 내용과 맞는지는 알 수 없다.
    실제로 '6사03-02'(인권)는 실재하지만 조선 후기 수업에는 맞지 않는다.
    의미 정합은 LLM 검수 R1/R7 의 몫이다.
    """
    if not db_path.exists():
        return [Problem("standards_exist", f"성취기준 DB 없음: {db_path} — scripts/seed_standards.py 먼저 실행")]

    conn = sqlite3.connect(db_path)
    try:
        problems = []
        for code in plan["standards"]:
            row = conn.execute("SELECT 1 FROM standards WHERE code = ?", (code,)).fetchone()
            if row is None:
                problems.append(Problem("standards_exist", f"성취기준 {code} 가 DB에 없음"))
        return problems
    finally:
        conn.close()


# NCIC 의 과목명은 교실에서 쓰는 이름과 다르다. 코드로만 조회하면 이 차이가 드러나지 않으므로
# 과목 대조를 하려면 별도 매핑이 필요하다.
SUBJECT_ALIASES = {
    "실과": "실과(기술 · 가정)/정보",
}


def check_standards_subject_match(plan: dict, db_path: Path) -> list[Problem]:
    """성취기준이 이 과목의 것인가.

    코드 존재 검사가 못 잡는 오류 하나를 더 잡는다 — 사회 수업에 실과 성취기준을 붙인 경우.
    같은 과목 안에서 엉뚱한 단원의 코드를 붙인 것은 여전히 못 잡는다(LLM 검수 R1/R7 의 몫).
    """
    if not db_path.exists():
        return []

    want = plan["meta"]["subject"]
    want_db = SUBJECT_ALIASES.get(want, want)

    conn = sqlite3.connect(db_path)
    try:
        problems = []
        for code in plan["standards"]:
            row = conn.execute("SELECT subject FROM standards WHERE code = ?", (code,)).fetchone()
            if row is not None and row[0] != want_db:
                problems.append(
                    Problem("standards_subject", f"{code} 는 '{row[0]}' 성취기준인데 수업 과목은 '{want}'")
                )
        return problems
    finally:
        conn.close()


def check_replacement_justified(plan: dict) -> list[Problem]:
    """교과서를 벗어난 활동에 근거가 있는가. (스키마와 이중 방어)"""
    problems = []
    for a in plan["activities"]:
        if a["source"] in ("대체", "혼합"):
            if not a.get("replaces"):
                problems.append(Problem("replacement", f"활동 {a['id']}: source={a['source']} 인데 replaces 없음"))
            if not a.get("rationale"):
                problems.append(Problem("replacement", f"활동 {a['id']}: source={a['source']} 인데 rationale 없음"))
    return problems


# ----------------------------------------------------------------- 세안 검사
#
# 아래는 전부 "약안으로는 못 하고 세안이라야 하는" 것을 지키는 검사다.
# 담임 판정(2026-07-29): "약안은 게임 내용을 모르겠더라."
# 실제로 같은 게임을 약안은 26자로, 세안은 절차·단서·문장틀까지 적는다.


def check_dialogue_present(plan: dict) -> list[Problem]:
    """세안인데 교사 대사가 없으면 세안이 아니다.

    blocks 를 하나도 안 쓴 지도안은 약안으로 본다(검사 안 함). 그러나 한 활동이라도
    blocks 를 쓰기 시작했으면 모든 활동이 T 발화를 가져야 한다 — 절반만 세안인 문서가
    가장 나쁘다. 교사가 어디까지 대본이 있는지 알 수 없어 수업 중에 멈춘다.
    """
    if not any(a.get("blocks") for a in plan["activities"]):
        return []

    problems = []
    for a in plan["activities"]:
        blocks = a.get("blocks") or []
        if not blocks:
            problems.append(
                Problem("dialogue", f"활동 {a['id']}({a.get('stage_label') or a['phase']}): 세안인데 교수·학습 활동 블록이 비었음")
            )
            continue
        speakers = [ln["speaker"] for b in blocks for ln in b.get("lines", [])]
        if "T" not in speakers:
            problems.append(
                Problem("dialogue", f"활동 {a['id']}: 교사 발화(T)가 한 줄도 없음 — 교사가 무엇을 말할지 알 수 없다")
            )
    return problems


def check_game_runnable(plan: dict) -> list[Problem]:
    """게임만 따로 읽어도 교실에서 굴릴 수 있는가.

    담임의 P1 판정 기준이 그대로 검사가 된 것이다.
    절차가 있는데 학생이 무슨 말을 채워 넣는지(sentence_stem)도,
    교사가 무엇을 말하는지(teacher_script)도 없으면 게임이 아니라 게임 이름이다.
    """
    problems = []
    for a in plan["activities"]:
        game = a.get("game")
        if not game:
            continue
        if not (game.get("sentence_stem") or game.get("teacher_script")):
            problems.append(
                Problem("game_runnable", f"활동 {a['id']} 게임 '{game['name']}': 절차만 있고 문장틀도 교사 대사도 없음")
            )
        if not game.get("clue_source") and game.get("answer_format"):
            problems.append(
                Problem(
                    "game_runnable",
                    f"활동 {a['id']} 게임 '{game['name']}': 답의 형태는 정했는데 무엇을 근거로 답하는지가 없음 — 추측이 찍기가 된다",
                    severity="warn",
                )
            )
    return problems


def _normalize_material(s: str) -> str:
    """'★단서 종이', '단서 종이(모둠별)', '슬라이드 5~7' 를 견주기 좋게 다듬는다."""
    s = s.strip().lstrip("★※").strip()
    s = re.sub(r"[（(].*?[)）]", "", s)
    s = re.sub(r"[0-9~\-–—쪽\s]+$", "", s)
    return s.strip()


def check_game_materials(plan: dict) -> list[Problem]:
    """게임에 필요한 물건이 활동 자료 목록에 올라와 있는가.

    실물 세안에서 실제로 빠져 있던 것이다 — 활동1 게임은 '단서 종이'로 굴러가는데
    자료(★) 칸에도 머리표 '학습 자료' 에도 단서 종이가 없다. 수업 전날 인쇄물을
    준비하는 사람은 자료 칸만 본다.
    """
    problems = []
    for a in plan["activities"]:
        game = a.get("game")
        if not game:
            continue
        have = {_normalize_material(m) for m in a.get("materials", [])}
        for need in game.get("materials", []):
            if _normalize_material(need) not in have:
                problems.append(
                    Problem(
                        "game_materials",
                        f"활동 {a['id']}: 게임에 '{need}' 가 필요한데 활동 자료 목록에 없음 — 준비물에서 누락된다",
                    )
                )
    return problems


# 순위·탈락을 금지하는 표현. 실과 지도안이 반복해서 쓰는 어휘를 그대로 가져왔다.
_RANK_WORDS = ("순위", "탈락", "등수", "1등", "속도 경쟁")


def check_competition_policy(plan: dict) -> list[Problem]:
    """게임의 경쟁 정책이 이 수업의 금지사항과 모순되지 않는가.

    담임 결정(2026-07-29): 경쟁 정책은 차시마다 고른다. 고를 수 있게 한 대신,
    '순위 공개 금지'라고 써 놓고 순위를 공개하는 게임을 넣는 일은 기계가 막는다.
    """
    problems = []
    banned = [p for p in plan.get("prohibitions", []) if any(w in p for w in _RANK_WORDS)]
    if not banned:
        return []

    for a in plan["activities"]:
        game = a.get("game")
        if not game:
            continue
        if game.get("competition_policy") == "순위공개":
            problems.append(
                Problem(
                    "competition_policy",
                    f"활동 {a['id']} 게임 '{game['name']}' 은 순위공개인데 이 수업의 금지사항에 {banned} 가 있음",
                )
            )
    return problems


def check_slide_ranges(plan: dict) -> list[Problem]:
    """슬라이드 배정이 겹치거나 비지 않는가.

    세안은 자료 칸에 '★슬라이드 5~7' 처럼 단계마다 슬라이드를 배정한다.
    겹치면 같은 장을 두 번 띄우게 되고, 비면 아무도 안 쓰는 장이 남는다.
    """
    ranges = [
        (a["slide_range"][0], a["slide_range"][1], a["id"])
        for a in plan["activities"]
        if a.get("slide_range")
    ]
    if not ranges:
        return []

    problems = []
    for start, end, aid in ranges:
        if start > end:
            problems.append(Problem("slide_range", f"활동 {aid}: 슬라이드 범위가 거꾸로다 ({start}~{end})"))

    ranges.sort()
    for (s1, e1, a1), (s2, e2, a2) in zip(ranges, ranges[1:]):
        if s2 <= e1:
            problems.append(Problem("slide_range", f"활동 {a1}({s1}~{e1}) 와 {a2}({s2}~{e2}) 의 슬라이드가 겹침"))
        elif s2 > e1 + 1:
            problems.append(
                Problem("slide_range", f"슬라이드 {e1 + 1}~{s2 - 1} 을 쓰는 활동이 없음", severity="warn")
            )
    return problems


def check_templated_structure_has_worksheet(plan: dict) -> list[Problem]:
    """활동지 칸으로 검증 가능한 구조를 쓰면서 활동지가 없으면 알린다.

    실패가 아니라 경고다. 실물 1차시 활동2는 '돌아가며 쓰기'를 쓰지만 활동지 대신
    '질문 띠지'를 돌린다 — 종이 형태만 다를 뿐 구조는 성립한다.
    다만 이 경우 활동지↔구조 역할 검증(cross_checks)이 통째로 건너뛰어지므로,
    검증 사각지대가 생겼다는 사실 자체를 남긴다.
    """
    kagan = json.loads((CONTRACTS / "kagan_structures.json").read_text(encoding="utf-8"))
    verifiable = {s["id"] for s in kagan["structures"] if s["worksheet_verifiable"]}

    problems = []
    for a in plan["activities"]:
        structure = a.get("kagan_structure")
        if structure in verifiable and not a.get("worksheet_items"):
            problems.append(
                Problem(
                    "templated_no_worksheet",
                    f"활동 {a['id']} 는 '{structure}'(활동지 칸으로 검증 가능한 구조)인데 "
                    "활동지 항목이 없어 구조↔활동지 역할 검증을 건너뛴다",
                    severity="warn",
                )
            )
    return problems


def run_all(plan: dict, db_path: Path | None = None) -> list[Problem]:
    problems = (
        check_minutes_sum(plan)
        + check_objective_coverage(plan)
        + check_kagan_usage(plan)
        + check_replacement_justified(plan)
        + check_dialogue_present(plan)
        + check_game_runnable(plan)
        + check_game_materials(plan)
        + check_competition_policy(plan)
        + check_slide_ranges(plan)
        + check_templated_structure_has_worksheet(plan)
    )
    if db_path is not None:
        problems += check_standards_exist(plan, db_path)
        problems += check_standards_subject_match(plan, db_path)
    return problems
