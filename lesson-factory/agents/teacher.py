"""교사 에이전트 — 약안 + 교과서 + 지도서 → 세안(LessonPlan JSON).

**LLM 호출 1회. JSON in, JSON out.** (CLAUDE.md C-3) 모델이 다른 모델을 부르지 않고,
도구도 받지 않는다. 파일을 읽고 검사를 돌리는 것은 전부 이 파이썬 코드가 한다.

재작업 루프는 여기 있다 (B-6, 최대 2회). 다시 부를 때 넘기는 것은 **기계 검사가 낸
문제 목록뿐**이다 — 모델의 이전 사고 과정을 되돌려 주지 않는다. 그걸 주면 모델이
자기가 쓴 근거를 다시 읽고 같은 자리에 눌러앉는다.

입력을 만드는 자리이기도 하다. 학습목표·쪽수는 **등록부에서** 오고, 성취기준 문구는
**DB에서** 온다 (B-1). 모델에게 "알아서 찾아라" 라고 하지 않는다.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator

from checks import Problem, has_errors, needs_review
from checks import plan_checks, textbook_checks
from core import materials as materials_mod
from core.llm import Client, LLMError

ROOT = Path(__file__).resolve().parent.parent
PROMPT = ROOT / "agents" / "prompts" / "teacher_sean.md"
SCHEMA = ROOT / "contracts" / "lesson_plan.schema.json"
KAGAN = ROOT / "contracts" / "kagan_structures.json"
STANDARDS_DB = ROOT / "curriculum" / "standards.sqlite"


@dataclass
class Result:
    plan: dict | None
    problems: list[Problem] = field(default_factory=list)
    attempts: int = 0
    missing_materials: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.plan is not None and not has_errors(self.problems)

    @property
    def needs_teacher(self) -> bool:
        return needs_review(self.problems)


# --------------------------------------------------------------------- 입력 만들기

def lookup_standards(codes: list[str], db_path: Path = STANDARDS_DB) -> list[dict]:
    """성취기준 문구는 **DB 조회로만** 가져온다 (CLAUDE.md B-1).

    없으면 빈 목록이 아니라 예외다. 문구 없이 프롬프트를 보내면 모델이 지어낸다.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"성취기준 DB 없음: {db_path} — scripts/seed_standards.py 를 먼저 돌린다")
    conn = sqlite3.connect(db_path)
    try:
        out = []
        for code in codes:
            row = conn.execute("SELECT code, text FROM standards WHERE code = ?", (code,)).fetchone()
            if row is None:
                raise LookupError(f"성취기준 {code} 가 DB에 없다 — 지어내지 않고 멈춘다")
            out.append({"code": row[0], "text": row[1]})
        return out
    finally:
        conn.close()


def build_input(
    *,
    subject: str,
    grade: int,
    semester: int,
    period: str,
    standards: list[str],
    group_count: int = 6,
    previous_preview: str | None = None,
    inbox: Path | None = None,
    registry_root: Path | None = None,
    db_path: Path = STANDARDS_DB,
) -> tuple[dict, materials_mod.Materials]:
    """프롬프트가 기대하는 입력 JSON 을 조립한다 (teacher_sean.md §입력)."""
    registry = textbook_checks.load_registry(subject, grade, semester, registry_root)
    lesson = textbook_checks.find_lesson(registry, period) if registry else None

    unit_entry = None
    if registry:
        for unit in registry["units"]:
            if any(l["period"] == period for l in unit["lessons"]):
                unit_entry = unit
                break

    mats = materials_mod.gather(
        subject=subject,
        grade=grade,
        semester=semester,
        unit=(unit_entry or {}).get("unit", ""),
        sub_unit=(unit_entry or {}).get("sub_unit"),
        textbook_pages=(lesson or {}).get("pages"),
        guide_pages=(lesson or {}).get("guide_pages"),
        inbox=inbox,
    )

    payload = {
        "request": {
            "subject": subject, "grade": grade, "semester": semester,
            "unit": (unit_entry or {}).get("unit"),
            "sub_unit": (unit_entry or {}).get("sub_unit"),
            "period": period,
        },
        "약안": mats.lesson_brief,
        "교과서": mats.textbook,
        "standards": lookup_standards(standards, db_path),
        # 등록돼 있지 않으면 null 이고, 프롬프트 2-1 이 "그때만 약안 것을 쓴다" 로 받는다
        "교과서목표": (lesson or {}).get("objective"),
        "소단원목표": [o["text"] for o in (unit_entry or {}).get("objectives", [])],
        "교과서쪽": (lesson or {}).get("pages"),
        "지도서": mats.teacher_guide,
        "지도서쪽": (lesson or {}).get("guide_pages"),
        "교과서차시": (lesson or {}).get("textbook_period"),
        "모둠": {"size": 4, "group_count": group_count},
        "kagan": json.loads(KAGAN.read_text(encoding="utf-8")),
        "이전_차시": previous_preview,
        "lessons": _lessons_learned(),
    }
    return payload, mats


def _lessons_learned() -> str | None:
    """수업 후 교훈 요약본. 없으면 None — 아직 수업을 안 했으니 정상이다."""
    path = ROOT / "feedback" / "lessons.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


# ------------------------------------------------------------------------ 생성

def _validate(plan: dict, db_path: Path, registry_root: Path | None) -> list[Problem]:
    """스키마 → 기계 검사 순서. 스키마가 깨지면 검사는 돌리지 않는다."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(plan))
    if errors:
        return [
            Problem("schema", f"{'/'.join(str(p) for p in e.absolute_path) or '(최상위)'}: {e.message}")
            for e in errors[:20]
        ]
    return plan_checks.run_all(plan, db_path if db_path.exists() else None, registry_root)


def _repair_note(problems: list[Problem]) -> str:
    """재작업 지시. **문제만 준다** — 이전 산출물도, 모델의 근거도 다시 주지 않는다."""
    lines = [f"- [{p.severity}] {p.check}: {p.message}" for p in problems if p.severity != "warn"]
    return (
        "앞선 출력이 기계 검사에서 걸렸다. 아래를 고쳐 **JSON 전체를 다시** 내라.\n"
        "설명하지 말고 JSON 만 출력한다.\n\n" + "\n".join(lines)
    )


def generate(
    client: Client,
    *,
    trace_id: str,
    payload: dict,
    max_revisions: int = 2,
    db_path: Path = STANDARDS_DB,
    registry_root: Path | None = None,
) -> Result:
    """세안을 만들고, 기계 검사를 통과할 때까지 최대 2회 고쳐 부른다."""
    prompt = PROMPT.read_text(encoding="utf-8")
    result = Result(plan=None)
    request = dict(payload)

    for attempt in range(max_revisions + 1):
        result.attempts = attempt + 1
        try:
            reply = client.call_json(agent="teacher", trace_id=trace_id, prompt=prompt, payload=request)
        except LLMError as exc:
            result.problems = [Problem("llm", str(exc))]
            return result

        plan = reply.data
        plan.setdefault("trace_id", trace_id)
        problems = _validate(plan, db_path, registry_root)
        result.plan, result.problems = plan, problems

        if not has_errors(problems):
            return result
        if attempt == max_revisions:
            break  # B-6 — 초과하면 ESCALATED 로 두고 사람을 부른다
        request = dict(payload) | {"수정지시": _repair_note(problems)}

    return result
