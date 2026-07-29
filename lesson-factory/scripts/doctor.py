#!/usr/bin/env python3
"""설치 진단 — 지금 무엇이 되고 무엇이 안 되는지 알려 준다.

    python scripts/doctor.py

설치 안내문은 시간이 지나면 틀려진다. 이 파일은 **지금 이 컴퓨터의 상태를 직접
확인해서** 알려 주므로 안내문보다 오래 맞는다.

없는 것을 발견하면 **고치는 명령까지 같이 인쇄한다.** "X 가 없습니다" 로 끝내면
사람이 다시 검색해야 한다.

LLM 을 호출하지 않는다. 인터넷도 쓰지 않는다.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK, WARN, BAD = "✅", "⚠️ ", "❌"


def line(mark: str, label: str, detail: str = "", fix: str = "") -> bool:
    print(f" {mark} {label}" + (f" — {detail}" if detail else ""))
    if fix:
        for row in fix.strip().splitlines():
            print(f"      → {row.strip()}")
    return mark == OK


def check_python() -> bool:
    version = sys.version_info
    if version >= (3, 11):
        return line(OK, "파이썬", f"{version.major}.{version.minor}.{version.micro}")
    return line(BAD, "파이썬", f"{version.major}.{version.minor} — 3.11 이상이 필요하다",
                "https://www.python.org/downloads/ 에서 설치. 설치할 때 'Add Python to PATH' 를 켠다")


def check_packages() -> bool:
    required = {"jsonschema": "계약 검증", "docx": "세안·활동지 .docx 렌더"}
    optional = {"anthropic": "API 키로 돌릴 때만 (구독제면 필요 없다)",
                "pptx": "슬라이드 렌더 — 아직 안 만들었다"}
    ok = True
    for name, why in required.items():
        if importlib.util.find_spec(name) is None:
            ok = line(BAD, f"{name}", why, "pip install -r requirements.txt") and ok
        else:
            line(OK, f"{name}", why)
    for name, why in optional.items():
        if importlib.util.find_spec(name) is None:
            line(WARN, f"{name} (선택)", why)
        else:
            line(OK, f"{name} (선택)", why)
    return ok


def check_engine() -> bool:
    """구독제 경로(Claude Code)와 API 경로 중 **하나만** 있으면 된다."""
    has_cli = shutil.which("claude") is not None
    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    if has_cli:
        line(OK, "Claude Code CLI", "구독제로 돈다 — API 키가 필요 없다")
    if has_key:
        line(OK, "ANTHROPIC_API_KEY", "API 경로도 쓸 수 있다 (종량제 별도 청구)")
    if has_cli or has_key:
        return True
    return line(BAD, "생성 엔진 없음", "Claude Code 도 API 키도 없다",
                "둘 중 하나:\n"
                "npm install -g @anthropic-ai/claude-code   (구독제, 권장)\n"
                ".env 에 ANTHROPIC_API_KEY 를 넣는다        (종량제 별도 청구)")


def check_standards_db() -> bool:
    path = ROOT / "curriculum" / "standards.sqlite"
    if not path.exists():
        return line(BAD, "성취기준 DB", "없다 — 이게 없으면 아무것도 못 만든다 (B-1)",
                    "python scripts/seed_standards.py")
    conn = sqlite3.connect(path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM standards").fetchone()[0]
    except sqlite3.Error:
        return line(BAD, "성취기준 DB", "표가 깨졌다", "python scripts/seed_standards.py")
    finally:
        conn.close()
    if count == 0:
        return line(BAD, "성취기준 DB", "비어 있다", "python scripts/seed_standards.py")
    return line(OK, "성취기준 DB", f"{count}개")


def check_registry() -> bool:
    folder = ROOT / "curriculum" / "textbook"
    files = sorted(folder.glob("*.json")) if folder.exists() else []
    if not files:
        return line(WARN, "교과서 등록부", "없다 — 학습목표 대조를 못 한다(경고만 나고 진행은 된다)")
    return line(OK, "교과서 등록부", " · ".join(f.stem for f in files))


def check_out_root() -> bool:
    """산출물이 어디로 떨어지는지, 그리고 **거기에 쓸 수 있는지**까지 본다.

    경로만 확인하고 넘어가면 수업 전날 `--write` 를 눌렀을 때 처음 실패한다.
    """
    sys.path.insert(0, str(ROOT))
    from core import config, paths  # noqa: E402  (경로를 넣은 뒤에 불러야 한다)

    config.load_dotenv()
    configured = os.getenv("LESSON_OUT", "").strip()
    root = paths.out_root()

    if not configured:
        return line(WARN, "산출물 위치", f"{root} (저장소 안)",
                    r'드라이브로 보내려면 .env 에:  LESSON_OUT=G:\내 드라이브\...\5학년\2학기')
    if not root.exists():
        return line(BAD, "산출물 위치", f"{root} — 그런 폴더가 없다",
                    "경로를 다시 확인한다. 구글 드라이브 데스크톱이 켜져 있어야 G: 가 보인다")
    probe = root / ".lesson-factory-쓰기시험"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return line(BAD, "산출물 위치", f"{root} — 쓸 수 없다 ({exc.__class__.__name__})",
                    "폴더 권한을 확인한다")
    return line(OK, "산출물 위치", f"{root}  (<과목>/<차시>/ 로 쌓인다)")


def check_materials() -> bool:
    """`materials/inbox/` 는 **사람이 채우는 자리**다 (A-2). 비어 있어도 실패는 아니다."""
    inbox = ROOT / "materials" / "inbox"
    if not inbox.exists() or not any(inbox.iterdir()):
        return line(WARN, "수업 자료 inbox", "비어 있다 — 약안·교과서 없이도 돌지만 품질이 떨어진다",
                    "materials/inbox/사회/약안/2단원_2-1_유교조선.md\n"
                    "materials/inbox/사회/교과서/사회-5-2-080.txt   (쪽마다 한 장)")
    parts = []
    for subject in sorted(p for p in inbox.iterdir() if p.is_dir()):
        counts = {kind.name: len(list(kind.glob("*"))) for kind in sorted(subject.iterdir()) if kind.is_dir()}
        parts.append(f"{subject.name}({', '.join(f'{k} {v}개' for k, v in counts.items())})")
    return line(OK, "수업 자료 inbox", " · ".join(parts))


def main() -> int:
    print("\n━━ lesson-factory 진단 ━━\n")
    print("■ 갖춰야 하는 것")
    hard = [check_python(), check_packages(), check_engine(), check_standards_db()]

    print("\n■ 설정")
    check_out_root()
    check_registry()
    check_materials()

    print()
    if all(hard):
        print("모두 준비됐다. 이렇게 돌린다:\n")
        print("   python run.py 사회 5 2 3/14 --standards 6사05-01           # 미리보기")
        print("   python run.py 사회 5 2 3/14 --standards 6사05-01 --write   # 저장\n")
        return 0
    print("❌ 위의 → 를 따라 고친 뒤 다시 돌린다.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
