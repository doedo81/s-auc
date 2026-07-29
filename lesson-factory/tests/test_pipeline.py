"""P2 배관 — 입력 조립 · LLM 어댑터 · 비용 기록 · 재작업 루프.

**이 파일은 LLM 을 호출하지 않는다.** 오프라인 녹음본과 가짜 클라이언트로 돈다.
테스트가 돈을 쓰기 시작하면 아무도 테스트를 돌리지 않고, 그러면 검사가 썩는다.

여기서 지키려는 것 네 가지:

1. 성취기준 문구는 **DB 조회로만** 온다 — 없으면 지어내지 않고 예외 (B-1)
2. 모든 호출의 토큰·비용이 `llm_calls` 에 남는다 (B-4)
3. 재작업은 **최대 2회**, 그리고 재작업 입력에 이전 산출물이 실리지 않는다 (B-6 · C-2)
4. 단가를 모르는 모델의 비용은 0 이 아니라 **None** — 상한이 조용히 무력해지면 안 된다
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import teacher  # noqa: E402
from checks import Problem, has_errors  # noqa: E402
from core import db as db_mod, materials as materials_mod  # noqa: E402
from core.config import Config  # noqa: E402
from core.llm import Client, CostLimitExceeded, LLMError, extract_json  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
CASSETTES = ROOT / "tests" / "cassettes"
TRACE = "사회-5-2-2_14차시"


def config(**over) -> Config:
    base = dict(api_key=None, model="claude-opus-5", effort="high", max_revisions=2,
                cost_limit_krw=None, usd_krw=None, school="신리초", class_name="5-5", class_size=24)
    return Config(**(base | over))


@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "bus.sqlite")
    yield c
    c.close()


# ------------------------------------------------------------------ JSON 꺼내기

@pytest.mark.parametrize("raw", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    '```\n{"a": 1}\n```',
    '설명이 붙어 왔다. {"a": 1} 끝.',
])
def test_extract_json_survives_wrapping(raw: str) -> None:
    """프롬프트가 '코드펜스 금지' 라고 해도 붙어 올 때가 있다. 그것 하나로 실패시키지 않는다."""
    assert extract_json(raw) == {"a": 1}


def test_extract_json_does_not_repair_broken_json() -> None:
    """감싼 것만 벗긴다. **내용은 고치지 않는다** — 고치기 시작하면 무엇을 받았는지 알 수 없다."""
    with pytest.raises(LLMError):
        extract_json('{"a": 1,,}')


# ---------------------------------------------------------------------- 비용

def test_unknown_model_costs_none_not_zero() -> None:
    """0 이면 '공짜' 와 '모름' 이 같은 값이 되고 비용 상한이 조용히 무력해진다."""
    assert db_mod.cost_usd("claude-opus-5", 1_000_000, 1_000_000) == pytest.approx(30.0)
    assert db_mod.cost_usd("어디서-온-모델", 1_000_000, 1_000_000) is None


def test_spent_ignores_unknown_cost_rows(conn) -> None:
    db_mod.record_llm_call(conn, trace_id="T", agent="teacher", model="x", cost_usd=None,
                           in_tokens=10, out_tokens=10)
    db_mod.record_llm_call(conn, trace_id="T", agent="teacher", model="claude-opus-5", cost_usd=1.5,
                           in_tokens=10, out_tokens=10)
    assert db_mod.spent_usd(conn, "T") == pytest.approx(1.5)


def test_cost_limit_is_none_without_exchange_rate() -> None:
    """환율을 모르면 상한도 없다. 아무 환율이나 넣으면 상한이 있는 척하게 된다."""
    assert config(cost_limit_krw=2000).cost_limit_usd is None
    assert config(cost_limit_krw=2000, usd_krw=1000).cost_limit_usd == pytest.approx(2.0)


def test_budget_guard_stops_the_next_call(conn) -> None:
    db_mod.record_llm_call(conn, trace_id=TRACE, agent="teacher", model="claude-opus-5",
                           cost_usd=5.0, in_tokens=1, out_tokens=1)
    client = Client(config(cost_limit_krw=1000, usd_krw=1000), conn, offline_dir=CASSETTES)
    with pytest.raises(CostLimitExceeded):
        client.call_json(agent="teacher", trace_id=TRACE, prompt="p", payload={})


# ------------------------------------------------------------------ 오프라인

def test_offline_replays_the_cassette(conn) -> None:
    client = Client(config(), conn, offline_dir=CASSETTES)
    reply = client.call_json(agent="teacher", trace_id=TRACE, prompt="p", payload={})
    assert reply.data["meta"]["subject"] == "사회"


def test_offline_says_which_file_is_missing(conn, tmp_path) -> None:
    client = Client(config(), conn, offline_dir=tmp_path)
    with pytest.raises(LLMError, match="녹음본이 없다"):
        client.call_json(agent="teacher", trace_id="없는차시", prompt="p", payload={})


# ---------------------------------------------------------------- 성취기준 (B-1)

def test_standards_text_comes_from_the_database() -> None:
    db_path = ROOT / "curriculum" / "standards.sqlite"
    if not db_path.exists():
        pytest.skip("standards.sqlite 없음 — scripts/seed_standards.py 먼저")
    [found] = teacher.lookup_standards(["6사05-01"], db_path)
    assert found["code"] == "6사05-01"
    assert "유교" in found["text"]


def test_missing_standard_raises_instead_of_inventing() -> None:
    db_path = ROOT / "curriculum" / "standards.sqlite"
    if not db_path.exists():
        pytest.skip("standards.sqlite 없음")
    with pytest.raises(LookupError):
        teacher.lookup_standards(["9사99-99"], db_path)


# ------------------------------------------------------------------ 입력 조립

def test_build_input_pulls_objective_and_pages_from_registry() -> None:
    db_path = ROOT / "curriculum" / "standards.sqlite"
    if not db_path.exists():
        pytest.skip("standards.sqlite 없음")
    payload, mats = teacher.build_input(
        subject="사회", grade=5, semester=2, period="2/14", standards=["6사05-01"],
    )
    assert payload["교과서목표"] == "한양의 건축물 이름에 담긴 유교 정신으로 조선이 유교의 나라임을 파악한다."
    assert payload["교과서쪽"] == [76, 79]
    assert payload["소단원목표"], "소단원 목표가 비어 있으면 차시 목표가 범위를 벗어나도 못 잡는다"
    assert payload["모둠"]["group_count"] == 6
    # inbox 가 비어 있는 것은 정상이다 — 없다고 말하고 넘어간다 (A-2)
    assert payload["교과서"] is None
    assert any("교과서" in m for m in mats.missing)


def test_missing_materials_are_reported_not_invented(tmp_path) -> None:
    mats = materials_mod.gather(
        subject="사회", grade=5, semester=2, unit="2. 단원", sub_unit="2-1 소단원",
        textbook_pages=[76, 79], guide_pages=[168, 175], inbox=tmp_path,
    )
    assert mats.textbook is None and mats.lesson_brief is None
    assert len(mats.missing) == 3
    assert mats.found == []


def test_inbox_files_are_actually_read(tmp_path) -> None:
    (tmp_path / "사회" / "교과서").mkdir(parents=True)
    (tmp_path / "사회" / "약안").mkdir(parents=True)
    (tmp_path / "사회" / "교과서" / "사회-5-2-076.txt").write_text("노상알현도", encoding="utf-8")
    (tmp_path / "사회" / "약안" / "2단원_2-1_유교조선.md").write_text("# 약안", encoding="utf-8")

    mats = materials_mod.gather(
        subject="사회", grade=5, semester=2, unit="2. 단원", sub_unit="2-1 유교조선",
        textbook_pages=[76, 77], guide_pages=None, inbox=tmp_path,
    )
    assert "노상알현도" in mats.textbook and "[76쪽]" in mats.textbook
    assert mats.lesson_brief == "# 약안"
    assert len(mats.found) == 2


# ------------------------------------------------------------------ 재작업 루프

class FakeClient:
    """정해 둔 답을 순서대로 돌려준다. 몇 번 불렸고 무엇을 받았는지 기록한다."""

    def __init__(self, replies: list[dict]):
        self.replies = replies
        self.payloads: list[dict] = []

    def call_json(self, *, agent, trace_id, prompt, payload):
        self.payloads.append(payload)
        from core.llm import Reply
        return Reply(copy.deepcopy(self.replies[min(len(self.payloads) - 1, len(self.replies) - 1)]),
                     0, 0, 0.0, "end_turn")


def good_plan() -> dict:
    return json.loads((FIXTURES / "사회-5-2-2단원-2차시.plan.json").read_text(encoding="utf-8"))


def broken_plan() -> dict:
    plan = good_plan()
    plan["activities"][0]["minutes"] = 6       # 5+12+15+8 이 41분이 된다 (스키마는 통과, 검사는 걸린다)
    return plan


def test_clean_output_calls_the_model_once() -> None:
    client = FakeClient([good_plan()])
    result = teacher.generate(client, trace_id="사회-5-2-2단원-2차시", payload={})
    assert result.ok and result.attempts == 1


def test_broken_output_is_sent_back_and_fixed() -> None:
    client = FakeClient([broken_plan(), good_plan()])
    result = teacher.generate(client, trace_id="사회-5-2-2단원-2차시", payload={})
    assert result.ok and result.attempts == 2


def test_revisions_stop_at_two(caplog) -> None:
    """B-6 — 재작업은 최대 2회. 초과하면 ESCALATED 로 두고 사람을 부른다."""
    client = FakeClient([broken_plan()])
    result = teacher.generate(client, trace_id="사회-5-2-2단원-2차시", payload={}, max_revisions=2)
    assert not result.ok
    assert result.attempts == 3          # 최초 1 + 재작업 2
    assert len(client.payloads) == 3
    assert has_errors(result.problems)


def test_revision_input_carries_problems_only(caplog) -> None:
    """C-2 앵커링 방지 — 재작업 입력에 **이전 산출물이 실리지 않는다.**

    모델에게 자기가 쓴 세안을 다시 주면 그 근거를 다시 읽고 같은 자리에 눌러앉는다.
    주는 것은 기계 검사가 낸 문제 목록뿐이다.
    """
    client = FakeClient([broken_plan(), good_plan()])
    teacher.generate(client, trace_id="사회-5-2-2단원-2차시", payload={"약안": "원문"})

    second = client.payloads[1]
    assert "수정지시" in second
    assert "minutes_sum" in second["수정지시"]
    assert second["약안"] == "원문"                       # 원래 입력은 그대로 간다
    assert "activities" not in json.dumps(second, ensure_ascii=False)   # 이전 세안은 없다


def test_schema_violation_is_caught_before_the_checks() -> None:
    """스키마가 깨졌으면 기계 검사를 돌리지 않는다 — 무엇이 깨졌는지가 흐려진다."""
    plan = good_plan()
    del plan["objectives"]
    result = teacher.generate(FakeClient([plan]), trace_id="사회-5-2-2단원-2차시", payload={}, max_revisions=0)
    assert not result.ok
    assert {p.check for p in result.problems} == {"schema"}


def test_trace_id_is_filled_in_when_the_model_forgets() -> None:
    plan = good_plan()
    del plan["trace_id"]
    result = teacher.generate(FakeClient([plan]), trace_id="사회-5-2-2단원-2차시", payload={})
    assert result.plan["trace_id"] == "사회-5-2-2단원-2차시"
