"""행정안전부 무더위쉼터(재난안전데이터공유플랫폼 DSSP-IF-10942)에서 관악구 쉼터만 받아 앱 형식 CSV로 저장한다.

실행 (저장소 폴더에서):
    python -m scripts.fetch_heat_shelters

- 키는 .env 의 SAFETYDATA_SHELTER_KEY 에서 읽는다.
- 출력: data/raw/shelters_heat_gwanak.csv (열: 쉼터명, 구분, 주소, 위도, 경도, 운영시간, 비고)
  data/raw/shelters.csv 로 바로 쓰지 않는다. 그 파일이 있으면 앱이 시연 모드에서도 가상 쉼터 대신 실제 쉼터를 쓴다.
  실제 모드로 바꿀 때 이동노동자 쉼터 파일과 합쳐서 shelters.csv 로 넣는다.
- 관악구인지는 주소 글자가 아니라 좌표가 관악구 행정동 경계 안에 있는지로 가린다.
- 전국 6만여 건이라 1,000건씩 받는다. 몇 분 걸린다.
- 항목 이름은 2026-11-23에 공개 자료로 확인한 것(RSTR_NM, LA, LO, FCLTY_TY 등)이고, 실제 응답으로는 아직 확인하지 못했다.
  이름이 다르면 FIELDS 의 후보만 고친다. 첫 건의 원본은 data/raw/shelters_heat_sample.json 에 남긴다.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import urllib.parse
import urllib.request

from backend import config, gwanak

URL = "https://www.safetydata.go.kr/V2/api/DSSP-IF-10942"
OUT = os.path.join(config.RAW_DIR, "shelters_heat_gwanak.csv")
SAMPLE = os.path.join(config.RAW_DIR, "shelters_heat_sample.json")
PAGE = 1000

# 앱 열 → 응답에서 찾아볼 항목 이름 후보(앞에서부터).
# 2026-11-23 실제 응답에서 확인한 이름: RSTR_NM, DTL_ADRES, XCORD, LO, WKDAY_OPER_BEGIN_TIME,
# WKDAY_OPER_END_TIME, USE_PSBL_NMPR, ARCD, YEAR (앞 14개만 봤다. LA/YCORD는 못 봤다)
FIELDS = {
    "name": ["RSTR_NM", "RSTR_FCLTY_NM", "FCLTY_NM"],
    "kind": ["FCLTY_TY_NM", "FCLTY_TY", "FCLTY_SCLAS_NM", "FCLTY_SE_NM"],
    "addr": ["RN_DTL_ADRES", "RN_ADRES", "DTL_ADRES", "ADRES", "RDNMADR"],
    "lat": ["LA", "YCORD", "LAT", "YCRD"],
    "lon": ["LO", "XCORD", "LOT", "XCRD"],
    "open": ["WKDAY_OPER_BEGIN_TIME", "WKDAY_OPN_TM"],
    "close": ["WKDAY_OPER_END_TIME", "WKDAY_END_TM"],
    "people": ["USE_PSBL_NMPR", "UTZTN_PSBLTY_TNOP"],
}
# 한국 위경도 범위. 이 밖이면 위경도가 아닌 다른 좌표계(TM 등)이므로 쓰지 않는다.
LAT_RANGE, LON_RANGE = (33.0, 39.5), (124.0, 132.0)


def pick(row: dict, key: str) -> str:
    for name in FIELDS[key]:
        v = row.get(name)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def hhmm(v: str) -> str:
    v = v.replace(":", "")
    return f"{v[:2]}:{v[2:4]}" if len(v) >= 4 and v[:4].isdigit() else v


def latlon(row: dict) -> tuple[float, float] | None:
    """응답 한 건에서 위경도를 꺼낸다. 값이 한국 범위 밖이면(다른 좌표계) 뒤집힌 경우만 바로잡고, 그래도 아니면 None."""
    try:
        lat, lon = float(pick(row, "lat")), float(pick(row, "lon"))
    except ValueError:
        return None
    if LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]:
        return lat, lon
    if LAT_RANGE[0] <= lon <= LAT_RANGE[1] and LON_RANGE[0] <= lat <= LON_RANGE[1]:
        return lon, lat          # 위도·경도가 바뀌어 들어온 경우
    return None


def to_app_row(row: dict) -> dict | None:
    """응답 한 건 → 앱 쉼터 목록 한 줄. 좌표가 없거나 관악구 밖이면 None."""
    pos = latlon(row)
    if not pos:
        return None
    lat, lon = pos
    if not gwanak.locate(lat, lon):
        return None
    o, c = hhmm(pick(row, "open")), hhmm(pick(row, "close"))
    people = pick(row, "people")
    return {"쉼터명": pick(row, "name"), "구분": "무더위쉼터" + (f"({pick(row, 'kind')})" if pick(row, "kind") else ""),
            "주소": pick(row, "addr"), "위도": f"{lat:.6f}", "경도": f"{lon:.6f}",
            "운영시간": f"평일 {o}~{c}" if o and c else "",
            "비고": (f"이용 가능 {people}명 · " if people else "") + "출처 행정안전부 무더위쉼터"}


def fetch(key: str, page: int) -> dict:
    q = urllib.parse.urlencode({"serviceKey": key, "returnType": "json", "pageNo": page, "numOfRows": PAGE})
    with urllib.request.urlopen(f"{URL}?{q}", timeout=30) as r:
        return json.load(r)


def main() -> None:
    key = os.getenv("SAFETYDATA_SHELTER_KEY", "").strip()
    if not key:
        sys.exit(".env 에 SAFETYDATA_SHELTER_KEY=... 를 넣고 다시 실행해 줘.")
    os.makedirs(config.RAW_DIR, exist_ok=True)
    out, page, seen = [], 1, 0
    while True:
        d = fetch(key, page)
        rows = d.get("body") or []
        if page == 1:
            if not rows:
                sys.exit(f"쉼터가 한 건도 안 왔어. 응답: {json.dumps(d, ensure_ascii=False)[:300].replace(key, '(키 가림)')}")
            with open(SAMPLE, "w", encoding="utf-8") as f:
                json.dump(rows[0], f, ensure_ascii=False, indent=2)
            if not pick(rows[0], "name"):
                sys.exit(f"쉼터 이름 항목을 못 찾았어. {SAMPLE} 을 열어 보고 FIELDS['name'] 후보를 고쳐 줘.\n항목: {', '.join(rows[0].keys())}")
            if not latlon(rows[0]):
                sys.exit(f"위경도 항목을 못 찾았거나 값이 한국 범위 밖이야. {SAMPLE} 을 열어 보고 FIELDS 의 lat·lon 후보를 고쳐 줘.\n"
                         f"지금 쓰는 후보: 위도 {FIELDS['lat']}, 경도 {FIELDS['lon']}\n항목: {', '.join(rows[0].keys())}")
            print(f"좌표 항목 확인: 첫 건 {latlon(rows[0])}")
        seen += len(rows)
        out += [r for r in map(to_app_row, rows) if r]
        print(f"{page}쪽: 누적 {seen}건, 관악구 {len(out)}곳")
        if len(rows) < PAGE:
            break
        page += 1
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["쉼터명", "구분", "주소", "위도", "경도", "운영시간", "비고"])
        w.writeheader()
        w.writerows(out)
    print(f"\n저장: {OUT} (관악구 {len(out)}곳)")


if __name__ == "__main__":
    main()
