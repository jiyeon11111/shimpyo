"""설정. 환경변수로 바꾼다 (.env.example 참고)."""
import os
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KST = timezone(timedelta(hours=9))

# 프로젝트 폴더의 .env를 읽는다 (이미 설정된 환경변수가 우선). 추가 패키지 없이.
_env = os.path.join(ROOT, ".env")
if os.path.exists(_env):
    for _line in open(_env, encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# 시연 모드: 날짜를 고정하고 미리 준비한 기상 데이터로만 판정한다. 발표장에서 인터넷이 끊겨도 동작.
DEMO_MODE = os.getenv("SHIMPYO_DEMO", "1") == "1"
DEMO_DATE = os.getenv("SHIMPYO_DEMO_DATE", "2026-08-03")
DEMO_START = os.getenv("SHIMPYO_DEMO_START", "14:00")
DEMO_LAT, DEMO_LON = 37.5552, 126.9222          # 마포구 서교동

# 기상청 단기예보 API (공공데이터포털 '디코딩' 인증키)
KMA_KEY = os.getenv("KMA_SERVICE_KEY", "")

DB_PATH = os.getenv("SHIMPYO_DB") or os.path.join(ROOT, "backend", "shimpyo.db")
DEMO_DIR = os.path.join(ROOT, "data", "demo")
RAW_DIR = os.path.join(ROOT, "data", "raw")
FRONTEND_DIR = os.path.join(ROOT, "frontend")


def now(at: str | None = None) -> datetime:
    """요청 시각. 시연 모드에서는 at(HH:MM 또는 ISO)을 시연 날짜에 붙여 쓴다."""
    if at:
        if "T" in at or " " in at:
            dt = datetime.fromisoformat(at.replace(" ", "T"))
        else:
            dt = datetime.fromisoformat(f"{DEMO_DATE if DEMO_MODE else datetime.now(KST).date()}T{at}")
        return dt.replace(tzinfo=None)
    if DEMO_MODE:
        return datetime.fromisoformat(f"{DEMO_DATE}T{DEMO_START}")
    return datetime.now(KST).replace(tzinfo=None)
