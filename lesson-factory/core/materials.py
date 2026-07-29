"""`materials/inbox/` 에서 약안·교과서·지도서를 읽는다.

CLAUDE.md A-2: **사람이 직접 내려받아 넣은 파일만 참조한다.** 자동 로그인·크롤링·
다운로드를 구현하지 않는다. 그래서 이 파일에는 네트워크 호출이 한 줄도 없다.

없는 자료는 **없다고 말하고 넘어간다.** 교과서 본문이 없으면 `null` 을 넘기고,
프롬프트가 "교과서 활동을 추측하지 말고 source 를 '대체' 로 두어라" 로 받는다.
빈 자리를 지어내서 채우는 것이 B-1 이 막으려던 바로 그 일이다.

찾는 자리 (`materials/inbox/<과목>/` 아래):

    약안/<단원>_<소단원>*.md          예: 2단원_2-1_유교조선.md
    교과서/<과목>-<학년>-<학기>-<쪽>.txt   예: 사회-5-2-076.txt  (쪽마다 한 장)
    지도서/<과목>-<학년>-<학기>-<쪽>.txt
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "materials" / "inbox"


@dataclass
class Materials:
    lesson_brief: str | None      # 약안 원문
    textbook: str | None          # 교과서 해당 쪽
    teacher_guide: str | None     # 지도서 해당 쪽
    missing: list[str]            # 사람에게 보여 줄 '없는 것' 목록
    found: list[str]              # 실제로 읽은 파일 (되짚기용)


def _label(path: Path) -> str:
    """되짚기용 경로. 저장소 밖을 가리켜도 터지지 않아야 한다.

    `relative_to` 만 쓰면 inbox 를 다른 곳에 두는 순간 자료를 읽어 놓고도 예외로 죽는다.
    경로 표기는 사람이 읽는 편의일 뿐이라, 그것 때문에 작업이 실패해서는 안 된다.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _read(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def _pages(subject: str, grade: int, semester: int, span: list[int] | None, folder: Path) -> tuple[str | None, list[str]]:
    """쪽수별 텍스트 파일을 이어 붙인다. 한 쪽이라도 없으면 있는 것만 모은다."""
    if not span:
        return None, []
    start, end = span[0], span[-1]
    chunks, found = [], []
    for page in range(start, end + 1):
        path = folder / f"{subject}-{grade}-{semester}-{page:03d}.txt"
        text = _read(path)
        if text:
            chunks.append(f"[{page}쪽]\n{text}")
            found.append(_label(path))
    return ("\n\n".join(chunks) if chunks else None), found


def find_brief(subject: str, unit: str, sub_unit: str | None, inbox: Path | None = None) -> tuple[str | None, str | None]:
    """약안 md 를 찾는다. 파일명이 제각각이라 **단원 번호로 헐겁게** 맞춘다.

    엄격하게 맞추면 파일 이름을 한 글자 바꿨다는 이유로 자료를 못 찾고, 그러면
    지어내기 시작한다. 헐겁게 찾고 어느 파일을 읽었는지 적어 두는 편이 안전하다.
    """
    folder = (inbox or INBOX) / subject / "약안"
    if not folder.exists():
        return None, None
    unit_no = re.match(r"\s*(\d+)", unit)
    keys = [k for k in (sub_unit.split()[0] if sub_unit else None, f"{unit_no.group(1)}단원" if unit_no else None) if k]
    for path in sorted(folder.glob("*.md")):
        if any(key in path.name for key in keys):
            return _read(path), _label(path)
    return None, None


def gather(
    *,
    subject: str,
    grade: int,
    semester: int,
    unit: str,
    sub_unit: str | None,
    textbook_pages: list[int] | None,
    guide_pages: list[int] | None,
    inbox: Path | None = None,
) -> Materials:
    base = inbox or INBOX
    missing: list[str] = []
    found: list[str] = []

    brief, brief_path = find_brief(subject, unit, sub_unit, base)
    if brief_path:
        found.append(brief_path)
    else:
        missing.append(f"약안 — {base / subject / '약안'} 에 이 단원 md 가 없다")

    textbook, tb_found = _pages(subject, grade, semester, textbook_pages, base / subject / "교과서")
    found += tb_found
    if textbook_pages and not textbook:
        missing.append(
            f"교과서 {textbook_pages[0]}~{textbook_pages[-1]}쪽 — "
            f"{base / subject / '교과서'} 에 쪽별 txt 가 없다 (교과서 활동을 추측하지 않는다)"
        )

    guide, guide_found = _pages(subject, grade, semester, guide_pages, base / subject / "지도서")
    found += guide_found
    if guide_pages and not guide:
        missing.append(
            f"지도서 {guide_pages[0]}~{guide_pages[-1]}쪽 — 각론이 스캔본이면 OCR 이 필요하다"
        )

    return Materials(brief, textbook, guide, missing, found)
