"""SQLite 저장소. 표준 라이브러리만 쓴다.

riders: 라이더 (MVP는 시연 라이더 1명)
rests:  쉼 기록. 시작할 때 한 줄 만들고, 종료할 때 정산 결과를 채운다.
"""
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS riders (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  home_sido TEXT,           -- 가입 기준(재원): 거주지
  stage TEXT NOT NULL DEFAULT 'A',   -- 데이터 연동 단계: A 앱 단독, B 정산 내역 연계, C 플랫폼 연동
  consent_at TEXT,          -- 위치 사용 동의 시각
  settle_status TEXT,       -- 정산 내역 대조: pending(대조 대기) | verified(확인) | mismatch(불일치)
  settle_at TEXT, settle_file TEXT
);
CREATE TABLE IF NOT EXISTS rests (
  id INTEGER PRIMARY KEY,
  rider_id INTEGER NOT NULL REFERENCES riders(id),
  start TEXT NOT NULL,      -- 'YYYY-MM-DDTHH:MM'
  end TEXT,
  place TEXT NOT NULL,      -- shelter | street
  verified INTEGER NOT NULL DEFAULT 0,  -- 쉼터 근처면 1, 그 밖은 위치 정지 확인 전 0
  nx INTEGER NOT NULL, ny INTEGER NOT NULL,   -- 판정 기준: 쉼을 시작한 위치의 격자
  sido TEXT, sgg TEXT, emd TEXT,              -- 집계 기준: 쉼을 시작한 위치의 행정구역
  rested_min INTEGER, paid_min INTEGER, amount INTEGER,
  virtual INTEGER NOT NULL DEFAULT 0,         -- 시연용 가상 기록이면 1
  -- 쉼을 시작할 때의 판정 근거 (나중에 정산·감사용)
  eligible INTEGER NOT NULL DEFAULT 0, reason TEXT,
  temp REAL, exposure_min INTEGER, usual_hourly INTEGER,
  -- 지급 기준: 쉼을 시작할 때의 연동 단계, 기준(none 지급 없음 | usual 평소 수입), 적용한 시급
  stage TEXT, basis TEXT, pay_hourly INTEGER
);
CREATE INDEX IF NOT EXISTS idx_rests_rider_start ON rests(rider_id, start);
"""
# 이전 버전 DB 파일에 새 열 추가
_NEW_COLS = ["eligible INTEGER NOT NULL DEFAULT 0", "reason TEXT", "temp REAL", "exposure_min INTEGER", "usual_hourly INTEGER",
             "stage TEXT", "basis TEXT", "pay_hourly INTEGER"]
_NEW_RIDER_COLS = ["stage TEXT NOT NULL DEFAULT 'A'", "consent_at TEXT", "settle_status TEXT", "settle_at TEXT", "settle_file TEXT"]


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        have = {r[1] for r in c.execute("PRAGMA table_info(rests)")}
        for col in _NEW_COLS:
            if col.split()[0] not in have:
                c.execute(f"ALTER TABLE rests ADD COLUMN {col}")
        have = {r[1] for r in c.execute("PRAGMA table_info(riders)")}
        for col in _NEW_RIDER_COLS:
            if col.split()[0] not in have:
                c.execute(f"ALTER TABLE riders ADD COLUMN {col}")
        if not c.execute("SELECT 1 FROM riders").fetchone():
            c.execute("INSERT INTO riders (id, name, home_sido) VALUES (1, '민수', '서울')")
        if config.DEMO_MODE and not c.execute("SELECT 1 FROM rests WHERE virtual = 1").fetchone():
            # 시연용: 지난주 쉼 기록 몇 건 (가상). 확정안 정산: 한 번에 30분치와 1만 원 중 작은 쪽 × 평소 시간당 수입
            past = [("2026-07-28T14:10", "2026-07-28T14:40", 30, 14_600), ("2026-07-30T13:30", "2026-07-30T13:55", 25, 18_900),
                    ("2026-07-31T15:00", "2026-07-31T15:40", 40, 13_900), ("2026-08-02T16:00", "2026-08-02T16:30", 30, 15_200)]
            for s, e, m, w in past:
                paid = min(m, 30)
                c.execute("""INSERT INTO rests (rider_id, start, end, place, verified, nx, ny, sido, sgg, emd,
                             rested_min, paid_min, amount, virtual, eligible, usual_hourly, stage, basis, pay_hourly)
                             VALUES (1, ?, ?, 'shelter', 1, 59, 125, '서울특별시', '관악구', '청룡동', ?, ?, ?, 1, 1, ?, 'C', 'usual', ?)""",
                          (s, e, m, paid, min(round(paid / 60 * w), 10_000), w, w))
