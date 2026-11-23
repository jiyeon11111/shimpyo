"""API 키가 제대로 들어갔는지 확인한다. 키 값은 화면에 찍지 않는다.

실행 (저장소 폴더에서):
    python -m scripts.check_keys

.env 에서 읽는 이름:
    KMA_SERVICE_KEY          공공데이터포털 일반 인증키(Decoding). 기상청 단기예보·영향예보에 쓴다
    SAFETYDATA_SHELTER_KEY   재난안전데이터공유플랫폼(safetydata.go.kr) 무더위쉼터 서비스 키
    KAKAO_REST_KEY           카카오 디벨로퍼스 REST API 키
    KMA_IMPACT_URL           (선택) 영향예보 요청주소. 활용신청 상세 화면의 폭염 영향예보 요청주소를 그대로 넣는다

기본 라이브러리만 쓴다.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from backend import config   # .env 를 읽어 환경변수로 올린다
from engine.grid import latlon_to_grid

KMA_NCST_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
SHELTER_URL = "https://www.safetydata.go.kr/V2/api/DSSP-IF-10942"
KAKAO_REGION_URL = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json"


def get(url: str, params: dict, headers: dict | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:   # 연결 실패, 시간 초과
        return 0, f"{type(e).__name__}: {e}"


def hide(text: str, *keys: str) -> str:
    """응답에 키가 섞여 나와도 화면에 찍히지 않게 가린다."""
    for k in keys:
        if k:
            text = text.replace(k, "(키 가림)").replace(urllib.parse.quote(k, safe=""), "(키 가림)")
    return text


def check_kma(key: str) -> tuple[bool, str]:
    now = datetime.now(config.KST) - timedelta(minutes=50)      # 실황은 매시 40분 이후에 그 시각 값이 나온다
    nx, ny = latlon_to_grid(config.DEMO_LAT, config.DEMO_LON)
    status, body = get(KMA_NCST_URL, {"serviceKey": key, "pageNo": 1, "numOfRows": 20, "dataType": "JSON",
                                      "base_date": now.strftime("%Y%m%d"), "base_time": now.strftime("%H00"), "nx": nx, "ny": ny})
    try:
        d = json.loads(body)["response"]
        if d["header"]["resultCode"] != "00":
            return False, f"기상청 응답 오류: {d['header']['resultMsg']}"
        vals = {i["category"]: i["obsrValue"] for i in d["body"]["items"]["item"]}
        return True, f"관악구청 격자({nx},{ny}) 지금 기온 {vals.get('T1H')}도, 습도 {vals.get('REH')}%"
    except Exception:
        return False, f"HTTP {status}. 응답 앞부분: {hide(body[:200], key)}"


def check_shelter(key: str) -> tuple[bool, str]:
    status, body = get(SHELTER_URL, {"serviceKey": key, "returnType": "json", "pageNo": 1, "numOfRows": 3})
    try:
        d = json.loads(body)
        rows = d.get("body") or []
        if not rows:
            return False, f"쉼터가 한 건도 안 왔어. 응답 앞부분: {hide(body[:200], key)}"
        total = d.get("totalCount") or (d.get("header") or {}).get("totalCount") or "?"
        return True, f"전국 {total}건 중 첫 건의 항목 이름: {', '.join(list(rows[0].keys())[:14])}"
    except Exception:
        return False, f"HTTP {status}. 응답 앞부분: {hide(body[:200], key)}"


def check_kakao(key: str) -> tuple[bool, str]:
    status, body = get(KAKAO_REGION_URL, {"x": config.DEMO_LON, "y": config.DEMO_LAT}, {"Authorization": f"KakaoAK {key}"})
    try:
        docs = json.loads(body)["documents"]
        h = next((x for x in docs if x.get("region_type") == "H"), docs[0])
        return True, f"관악구청 좌표 → {h['address_name']}"
    except Exception:
        return False, f"HTTP {status}. 응답 앞부분: {hide(body[:200], key)}"


def check_impact(key: str, url: str) -> tuple[bool, str]:
    status, body = get(url, {"serviceKey": key, "pageNo": 1, "numOfRows": 5, "dataType": "JSON"})
    ok = status == 200 and "SERVICE_KEY" not in body.upper() and "ERROR" not in body.upper()[:300]
    return ok, f"HTTP {status}. 응답 앞부분: {hide(body[:300], key)}"


def main() -> None:
    kma, shelter, kakao = (os.getenv(n, "").strip() for n in ("KMA_SERVICE_KEY", "SAFETYDATA_SHELTER_KEY", "KAKAO_REST_KEY"))
    impact_url = os.getenv("KMA_IMPACT_URL", "").strip()
    jobs = [("기상청 단기예보", "KMA_SERVICE_KEY", kma, lambda: check_kma(kma)),
            ("행정안전부 무더위쉼터", "SAFETYDATA_SHELTER_KEY", shelter, lambda: check_shelter(shelter)),
            ("카카오 로컬", "KAKAO_REST_KEY", kakao, lambda: check_kakao(kakao))]
    if impact_url:
        jobs.append(("기상청 영향예보", "KMA_SERVICE_KEY", kma, lambda: check_impact(kma, impact_url)))
    bad = 0
    for name, var, key, fn in jobs:
        if not key:
            print(f"[안 넣음] {name}: .env 에 {var}= 가 비어 있어")
            bad += 1
            continue
        ok, msg = fn()
        print(f"[{'성공' if ok else '실패'}] {name}: {msg}")
        bad += 0 if ok else 1
    if not impact_url:
        print("[건너뜀] 기상청 영향예보: .env 에 KMA_IMPACT_URL(요청주소)을 넣으면 같이 확인해. 키는 단기예보와 같은 KMA_SERVICE_KEY 를 써")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
