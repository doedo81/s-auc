"""지도안 단독 검증 — 다른 산출물 없이 지도안만 보고 판단할 수 있는 것."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import Problem


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


def run_all(plan: dict, db_path: Path | None = None) -> list[Problem]:
    problems = (
        check_minutes_sum(plan)
        + check_objective_coverage(plan)
        + check_kagan_usage(plan)
        + check_replacement_justified(plan)
    )
    if db_path is not None:
        problems += check_standards_exist(plan, db_path)
    return problems
