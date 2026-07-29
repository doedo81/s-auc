"""환경 설정 한 곳. `.env` 는 읽기만 하고 절대 쓰지 않는다 (CLAUDE.md B-3).

값이 없을 때 **기본값을 지어내지 않는 것**이 이 파일의 규칙이다. API 키가 없으면
없다고 말하고 멈춘다. 환율이 없으면 원화를 계산하지 않고 달러로만 보여 준다.
숫자를 지어내면 '비용 상한' 이 상한 노릇을 못 한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# CLAUDE.md F — 계획 수립(교사)·검수는 opus, effort high.
DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "high"


def load_dotenv(path: Path | None = None) -> None:
    """`.env` 를 os.environ 에 얹는다. **이미 있는 값은 덮지 않는다.**

    python-dotenv 를 쓰지 않는 이유는 하나다 — 이 프로젝트는 표준 라이브러리로
    돌아가는 것을 목표로 하고, 형식이 `KEY=value` 한 줄뿐이라 파서가 필요 없다.
    """
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Config:
    api_key: str | None
    model: str
    effort: str
    max_revisions: int
    cost_limit_krw: float | None
    usd_krw: float | None
    school: str
    class_name: str
    class_size: int

    @property
    def cost_limit_usd(self) -> float | None:
        """원화 상한을 달러로 옮긴다. **환율을 모르면 상한도 없다.**

        여기서 아무 환율이나 넣으면 상한이 조용히 틀린 값이 된다 — 상한이 있는 척하는
        것이 상한이 없는 것보다 나쁘다. 모르면 None 을 돌려주고, 호출자가 '상한 없음'
        을 사람에게 알린다 (침묵 금지, CLAUDE.md C-5).
        """
        if self.cost_limit_krw is None or self.usd_krw is None:
            return None
        return self.cost_limit_krw / self.usd_krw


def _float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def load(env_path: Path | None = None) -> Config:
    load_dotenv(env_path)
    return Config(
        api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        model=os.getenv("LESSON_MODEL", DEFAULT_MODEL),
        effort=os.getenv("LESSON_EFFORT", DEFAULT_EFFORT),
        max_revisions=int(os.getenv("MAX_REVISIONS", "2")),
        cost_limit_krw=_float("COST_LIMIT_KRW_PER_JOB"),
        usd_krw=_float("USD_KRW"),
        school=os.getenv("SCHOOL_NAME", "신리초"),
        class_name=os.getenv("CLASS_NAME", "5-5"),
        class_size=int(os.getenv("CLASS_SIZE", "24")),
    )
