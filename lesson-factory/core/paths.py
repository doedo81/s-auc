"""산출물이 어디에 떨어지는가.

담임 요구(2026-07-29): *"내가 컴퓨터를 켜놓으면 5학년 2학기 폴더에 다운받아 줬으면
좋겠는데. `G:\\내 드라이브\\도학원\\교육자료_통합보관소\\2026학년도\\5학년\\2학기`
여기 경로로 각 과목별로."*

그래서 배치는 이렇게 한다.

    <뿌리>/<과목>/<trace_id>/<파일>

`G:` 는 구글 드라이브 데스크톱이 물린 드라이브다. 거기에 쓰면 동기화는 드라이브가
알아서 한다 — 우리가 업로드 코드를 짤 일이 없고, **저작권 규칙과도 맞는다**:
선생님 개인 드라이브는 공개 저장소가 아니다 (CLAUDE.md A-3 은 공개 저장소·공개 URL 을
막는 것이지 개인 보관을 막는 게 아니다).

뿌리를 정하는 순서:

    1. CLI 의 `--out`
    2. `.env` 의 `LESSON_OUT`      ← 한 번 적어 두면 매번 안 쳐도 된다
    3. 저장소 안 `artifacts/`      ← 기본값. .gitignore 대상이다
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = ROOT / "artifacts"


def out_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    configured = os.getenv("LESSON_OUT", "").strip()
    return Path(configured) if configured else DEFAULT_ROOT


def subject_of(trace_id: str) -> str:
    """`사회-5-2-2단원-2차시` → `사회`.

    과목은 trace_id 첫 마디다. 지도안에는 `meta.subject` 가 있지만 활동지에는 없어서,
    둘 다 같은 규칙으로 폴더를 고르려면 trace_id 에서 뽑는 편이 어긋나지 않는다.
    """
    head = trace_id.split("-", 1)[0].strip()
    return head or "기타"


def lesson_dir(trace_id: str, root: Path | None = None, *, subject: str | None = None) -> Path:
    """이 차시의 산출물이 모이는 폴더. **만들지는 않는다** (dry_run 이 기본, B-2)."""
    return out_root(root) / (subject or subject_of(trace_id)) / trace_id
