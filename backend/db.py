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
  home_sido TEXT            -- 가입 기준(재원): 거주지
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
  virtual INTEGER NOT NULL DEFAULT 0          -- 시연용 가상 기록이면 1
);
CREATE INDEX IF NOT EXISTS idx_rests_rider_start ON rests(rider_id, start);
"""


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
        if not c.execute("SELECT 1 FROM riders").fetchone():
            c.execute("INSERT INTO riders (id, name, home_sido) VALUES (1, '민수', '서울')")
        if config.DEMO_MODE and not c.execute("SELECT 1 FROM rests WHERE virtual = 1").fetchone():
            # 시연용: 지난주 쉼 기록 몇 건 (가상)
            past = [("2026-07-28T14:10", "2026-07-28T15:20", 70), ("2026-07-30T14:30", "2026-07-30T16:00", 90),
                    ("2026-07-31T15:00", "2026-07-31T16:20", 80), ("2026-08-02T14:00", "2026-08-02T15:00", 60)]
            for s, e, m in past:
                c.execute("""INSERT INTO rests (rider_id, start, end, place, verified, nx, ny, sido, sgg, emd,
                             rested_min, paid_min, amount, virtual) VALUES (1, ?, ?, 'shelter', 1, 59, 126,
                             '서울특별시', '마포구', '서교동', ?, ?, ?, 1)""", (s, e, m, m, round(m / 60 * 17210)))
