"""인쇄량 검증 — 나눠 줄 수 있는 분량인가.

담임 요구(2026-07-29):

    "활동지를 애들한테 나눠줄 때는 최대한 한 장이나 두 장 양면 복사할 수 있게.
     더 많으면 나한테 좀 보여줘. 그래야 수정 좀 하고 나눠주게.
     안 그러면 인쇄량이 너무 많아지지.
     모둠은 여섯 개니까 여섯 모둠한테 나눠줄 때는 다양하게 나눠줄 순 있어."

그래서 규칙이 둘로 갈린다.

    개인 배부   1면, 많아야 2면(양면 한 장). 넘으면 **담임 확인으로 올린다**
    모둠 배부   분량 제한 없음. 모둠마다 다른 것을 줘도 된다

넘쳤을 때 실패시키지 않는 이유가 있다. 자를 곳을 정하는 것은 수업을 아는 사람의
판단이고, 기계가 임의로 자르면 학습에 필요한 칸이 날아간다. 그래서 막지 않고
**보여 준다.** 실제 인쇄 결정은 사람이 한다.
"""

from __future__ import annotations

from . import Problem

# 개인 배부 상한. 2면 = 양면 한 장 = 학생 한 명당 종이 한 장.
PERSONAL_PAGE_LIMIT = 2

DEFAULT_GROUP_COUNT = 6  # 담임 확인 (2026-07-29)


def check_print_budget(plan: dict, worksheet: dict) -> list[Problem]:
    """개인 배부 활동지가 양면 한 장 안에 들어가는가."""
    distribution = worksheet.get("distribution", "개인")
    pages = worksheet.get("pages", 1)

    if distribution != "개인":
        return []

    if pages > PERSONAL_PAGE_LIMIT:
        return [
            Problem(
                "print_budget",
                f"개인 배부 활동지가 {pages}면 — 양면 한 장({PERSONAL_PAGE_LIMIT}면)을 넘는다. "
                "자를 곳을 담임이 정해야 하므로 배부 전에 확인을 받는다",
                severity="review",
            )
        ]
    return []


def sheets_needed(plan: dict, worksheet: dict, class_size: int) -> dict:
    """실제로 몇 장을 찍게 되는지. 담임 승인 카드에 그대로 들어간다."""
    distribution = worksheet.get("distribution", "개인")
    pages = worksheet.get("pages", 1)
    duplex = worksheet.get("duplex", True)

    group_count = (plan.get("group_setup") or {}).get("group_count") or DEFAULT_GROUP_COUNT
    copies = {"개인": class_size, "짝": -(-class_size // 2), "모둠": group_count}[distribution]

    per_copy = -(-pages // 2) if duplex else pages
    return {
        "distribution": distribution,
        "copies": copies,
        "pages": pages,
        "duplex": duplex,
        "sheets": copies * per_copy,
    }


def summary_line(plan: dict, worksheet: dict, class_size: int) -> str:
    """한 줄 요약. 예: '개인 24부 × 2면 양면 = 종이 24장'"""
    s = sheets_needed(plan, worksheet, class_size)
    how = "양면" if s["duplex"] and s["pages"] > 1 else "단면"
    return f"{s['distribution']} {s['copies']}부 × {s['pages']}면 {how} = 종이 {s['sheets']}장"


def run_all(plan: dict, worksheet: dict) -> list[Problem]:
    return check_print_budget(plan, worksheet)
