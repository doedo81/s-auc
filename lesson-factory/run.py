#!/usr/bin/env python3
"""세안 자동 생성 — 한 줄로 돌린다.

    python3 run.py 사회 5 2 3/14 --standards 6사05-01              # dry_run
    python3 run.py 사회 5 2 3/14 --standards 6사05-01 --write       # 저장
    python3 run.py 사회 5 2 3/14 --standards 6사05-01 --offline     # LLM 없이 녹음본으로

CLAUDE.md B-2: **파일 쓰기는 dry_run 이 기본이다.** `--write` 를 줄 때만 저장한다.

돌아가는 순서는 항상 같다.

    등록부·DB·inbox 에서 입력 조립
      → 교사 에이전트 1회 호출
      → 스키마 → 기계 검사 (실패하면 최대 2회 재작업, B-6)
      → 세안 .docx 렌더
      → 담임에게 보고

기계 검사가 실패하면 **LLM 검수를 호출하지 않는다** (C-1). 아직 검수자가 붙지
않았지만 자리는 여기다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents import teacher                              # noqa: E402
from checks import has_errors, needs_review             # noqa: E402
from core import config as config_mod, db as db_mod, paths  # noqa: E402
from core.llm import ClaudeCodeClient, Client, CostLimitExceeded, LLMError  # noqa: E402

ROOT = Path(__file__).resolve().parent


def _make_client(cfg, conn, args):
    """어떤 길로 부를지 고른다.

    담임은 정액제다(2026-07-29 *"난 정액제인데 API 키를 꼭 써야 돼?"*).
    **API 키는 종량제 별도 청구**라서 구독과 지갑이 다르다 — 구독을 쓰려면
    Claude Code CLI 를 헤드리스로 부르는 쪽이 맞다. 그래서 기본값은
    '키가 있으면 API, 없으면 Claude Code' 다.
    """
    if args.offline:
        return Client(cfg, conn, offline_dir=ROOT / "tests" / "cassettes")
    if args.backend == "api":
        return Client(cfg, conn)
    if args.backend == "claude-code":
        return ClaudeCodeClient(cfg, conn)
    if cfg.api_key:
        return Client(cfg, conn)
    if ClaudeCodeClient.available():
        print("ℹ️  API 키가 없어 Claude Code CLI 로 돈다 (구독제). --backend api 로 바꿀 수 있다.")
        return ClaudeCodeClient(cfg, conn)
    raise SystemExit("❌ API 키도 없고 claude CLI 도 없다. 둘 중 하나는 있어야 한다.")


def _report(result: teacher.Result, cfg, conn, trace_id: str, client=None) -> None:
    """담임이 읽는 요약. **침묵 금지** — 잘 됐든 안 됐든 한 줄은 남긴다 (C-5)."""
    spent = db_mod.spent_usd(conn, trace_id)
    print(f"\n━━ {trace_id} ━━")
    label = "환산액(구독제면 실제 청구 아님)" if isinstance(client, ClaudeCodeClient) else "비용"
    print(f"호출 {result.attempts}회 · {label} ${spent:.4f}" + (
        f" (상한 ${cfg.cost_limit_usd:.4f})" if cfg.cost_limit_usd is not None
        else "  ⚠️ 비용 상한 없음 — .env 의 USD_KRW 가 비어 있어 원화 상한을 달러로 옮기지 못했다"
    ))

    if result.missing_materials:
        print("\n📭 없는 자료 (materials/inbox/ 에 사람이 넣어야 한다 — A-2)")
        for item in result.missing_materials:
            print(f"   · {item}")
    if result.sources:
        print(f"\n📚 읽은 자료 {len(result.sources)}개: " + " · ".join(result.sources[:4])
              + (f" 외 {len(result.sources) - 4}개" if len(result.sources) > 4 else ""))

    if result.problems:
        print(f"\n🔍 기계 검사 — 문제 {len(result.problems)}건")
        for problem in result.problems:
            print(f"   {problem}")
    else:
        print("\n🔍 기계 검사 통과")

    if result.needs_teacher:
        print("\n🖐 담임 확인이 필요한 항목이 있다 — 위 🖐 표시를 보라 (막지 않고 올린다)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="약안 + 교과서 + 지도서 → 세안 JSON · .docx")
    ap.add_argument("subject")
    ap.add_argument("grade", type=int)
    ap.add_argument("semester", type=int)
    ap.add_argument("period", help="'3/14' 형태 — 등록부 조회 키")
    ap.add_argument("--standards", nargs="+", required=True, help="성취기준 코드 (DB에 실재해야 한다)")
    ap.add_argument("--previous-preview", default=None, help="직전 차시의 차시 예고 (도입에서 이어 받는다)")
    ap.add_argument("--offline", action="store_true", help="LLM 없이 tests/cassettes/ 녹음본으로 돌린다")
    ap.add_argument("--backend", choices=["auto", "claude-code", "api"], default="auto",
                    help="auto = API 키가 있으면 API, 없으면 Claude Code CLI(구독제)")
    ap.add_argument("--write", action="store_true", help="실제로 파일을 쓴다 (기본은 dry_run)")
    ap.add_argument("--out", type=Path, default=None,
                    help="산출물 뿌리. 없으면 .env 의 LESSON_OUT, 그것도 없으면 artifacts/. "
                         r"구글 드라이브 폴더를 그대로 줘도 된다 (예: 'G:\내 드라이브\...\2학기')")
    args = ap.parse_args(argv)

    cfg = config_mod.load()
    trace_id = f"{args.subject}-{args.grade}-{args.semester}-{args.period.replace('/', '_')}차시"
    conn = db_mod.connect()

    try:
        payload, mats = teacher.build_input(
            subject=args.subject, grade=args.grade, semester=args.semester,
            period=args.period, standards=args.standards,
            previous_preview=args.previous_preview,
        )
    except (FileNotFoundError, LookupError) as exc:
        print(f"❌ 입력을 만들지 못했다: {exc}", file=sys.stderr)
        return 2

    client = _make_client(cfg, conn, args)

    try:
        result = teacher.generate(client, trace_id=trace_id, payload=payload,
                                  max_revisions=cfg.max_revisions)
    except CostLimitExceeded as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 3

    result.missing_materials = mats.missing
    result.sources = mats.found
    _report(result, cfg, conn, trace_id, client)

    if not result.ok:
        print(f"\n❌ {result.attempts}회 시도 후에도 검사를 통과하지 못했다 → ESCALATED (B-6)", file=sys.stderr)
        return 1

    folder = paths.lesson_dir(trace_id, args.out)
    plan_path = folder / f"{trace_id}.plan.json"
    docx_path = folder / f"{trace_id}-세안-v1.docx"

    if not args.write:
        print(f"\n[dry_run] 저장하려면 --write\n   {plan_path}\n   {docx_path}")
        return 0

    folder.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(result.plan, ensure_ascii=False, indent=2), encoding="utf-8")
    db_mod.record_artifact(conn, trace_id, "plan", plan_path)
    print(f"\n저장함: {plan_path}")

    try:
        from render import sean_docx
        sean_docx.build(result.plan, teacher.STANDARDS_DB if teacher.STANDARDS_DB.exists() else None).save(docx_path)
        db_mod.record_artifact(conn, trace_id, "sean_docx", docx_path)
        print(f"저장함: {docx_path}")
    except ImportError:
        print("⚠️ python-docx 가 없어 .docx 는 건너뛰었다 (JSON 은 저장됐다)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
