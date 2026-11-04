# 쉼표

폭염 시간에 쉰 배달 라이더에게 쉰 만큼 소득을 보전하는 앱과 판정 엔진.
기상청 격자 체감온도로 보전 구간을 판정하고, 라이더가 누른 쉼 시작·종료로 보전 시간과 금액을 계산한다.

## 바로 실행 (VS Code)

```
python -m venv .venv
.venv\Scripts\activate          # macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # Windows: copy .env.example .env
uvicorn backend.main:app --reload --port 8000
```

브라우저에서 http://localhost:8000 을 열면 앱이 뜬다. API 문서는 http://localhost:8000/docs.
VS Code에서는 실행 및 디버그(Ctrl+Shift+D)에서 "쉼표 서버 (FastAPI)"를 고르고 F5.

설치 없이 먼저 보고 싶으면 `python -m backend.serve_stdlib` (파이썬 기본 라이브러리만 쓰는 같은 API 서버, 8000번 포트).

## 구조

```
frontend/   화면 (HTML·CSS·JS, 설치형 웹앱)   index.html, style.css, app.js, logo.js, sw.js
backend/    API 서버
  main.py          FastAPI 경로 정의 (요청을 services로 넘기기만 함)
  serve_stdlib.py  같은 API를 기본 라이브러리로 띄우는 서버
  services.py      실제 동작: 현재 판정, 쉼 시작·종료, 내역, 쉼터, 리포트
  weather.py       기상청 단기예보 호출 (시연 모드는 data/demo의 파일)
  shelters.py      가까운 쉼터 찾기, 150m 안이면 쉼터 인정
  db.py            SQLite (riders, rests)
  config.py        환경변수 (.env)
engine/     판정 엔진: 체감온도, 단계 규칙, 분 단위 정산, 기상청 격자 변환
analysis/   분석 1~5, 온열질환 위험 모델
tests/      엔진 17개 + 서비스 9개 테스트  →  python -m pytest -q
data/demo/  시연용 가상 기상·쉼터
```

## API

| 메서드 | 경로 | 하는 일 |
|---|---|---|
| GET | `/api/config` | 시연 모드 여부, 시급, 하루·한 달 한도 |
| GET | `/api/now?lat&lon` | 이 위치 격자의 체감온도, 단계, 지금 쉬면 받는지, 언제까지·언제부터, 가장 가까운 쉼터 |
| POST | `/api/rest/start` | 쉬기 시작 `{rider_id, lat, lon, place: auto\|shelter\|street}` (auto: 쉼터 150m 안이면 쉼터) |
| GET | `/api/rest/current` | 쉬는 중이면 지금까지 잠정 보전 |
| POST | `/api/rest/stop` | 쉼 종료, 분 단위 정산 후 저장 |
| GET | `/api/history` | 오늘 기록, 이번 달 합계, 남은 한도, 최근 7일 |
| GET | `/api/shelters?lat&lon&kind=rider` | 가까운 쉼터 |
| GET | `/api/report?lat&lon` | 지자체·보험사용: 주변 7×7 격자 위험도, 보전 시간, 쉬지 못한 위험 시간 |
| POST | `/api/demo/reset` | 시연 날짜에 눌러 만든 기록 지우기 |

시연 모드에서는 모든 요청에 `at=HH:MM`을 붙여 시각을 바꿀 수 있다.

## 시연 모드와 실제 모드

- **시연 모드 (`SHIMPYO_DEMO=1`, 기본)**: 날짜를 2026-08-03으로 고정하고 `data/demo`의 가상 기상값, 가상 쉼터 5곳, 가상 지난 기록 4건, 리포트용 가상 라이더 300명을 쓴다. 인터넷 없이 발표장에서 동작한다. 화면 위 시연 막대로 시각을 옮기거나 재생한다. **이 값들은 모두 지어낸 것이다. 결과로 인용하지 않는다.**
- **실제 모드 (`SHIMPYO_DEMO=0`)**: 공공데이터포털에서 "기상청_단기예보 조회서비스" 인증키를 받아 `.env`의 `KMA_SERVICE_KEY`에 넣는다. 브라우저 위치를 쓰고, 기온·습도 예보로 체감온도를 계산한다 (30분 캐시).
- 실제 쉼터 목록: 행정안전부 무더위쉼터와 지자체 이동노동자 쉼터를 `data/raw/shelters.csv`로 넣는다 (열: 쉼터명, 구분, 주소, 위도, 경도, 운영시간, 비고).
- 동 이름 표시: 기상청 격자-행정구역 표(`data/raw/kma_grid.csv`)를 넣으면 격자 대신 시군구·읍면동이 나온다.

## MVP에서 가정한 것

- 운행 중이었는지(플랫폼 운행 기록)는 확인하지 않고 참으로 둔다. 플랫폼 협약 후 붙일 자리.
- 라이더는 1명(민수, id 1)으로 고정. 로그인 없음.
- 쉼터 밖 쉼은 위치가 멈춰 있는지 확인하는 단계가 들어갈 자리만 있고, 시연 모드에서는 바로 인정한다.

## 엔진과 분석

### 구성

| 파일 | 하는 일 |
|---|---|
| `engine/heat.py` | 기온·습도로 체감온도 계산 (기상청 여름철 산출식, 2022.6 적용) |
| `engine/rules.py` | 체감온도 단계별 지급 구간 판정. 임계값은 `RULES` 표만 고치면 됨 |
| `engine/payout.py` | 라이더 하루 정산: 운행 기록, 휴식 여부, 하루·한 달 상한 |
| `tests/test_engine.py` | 규칙이 의도대로 작동하는지 확인하는 테스트 17개 (분석용 계산이 엔진과 같은지 포함) |
| `demo.py` | 가상 폭염일 하루, 라이더 3명 예시 |
| `analysis/` | 분석 1~5와 온열질환 위험 예측 모델. 실행 방법은 `data/README.md` |
| `data/README.md` | 받은 데이터를 넣을 파일 이름과 열 규칙 |

### 실행

```
pip install pytest pandas numpy matplotlib scikit-learn
python -m pytest -q
python demo.py
python analysis/make_sample_data.py   # 실제 데이터가 없을 때 가상 데이터 생성
python analysis/run_all.py            # 분석 1~5, 모델 → outputs/
```

| 스크립트 | 질문 | 결과 |
|---|---|---|
| `a1_delivery_vs_heat.py` | 폭염일 하루당 배달 거래액은 몇 % 늘어나나 | 이중축 차트, 증가율과 95% 구간 |
| `a2_threshold.py` | 체감온도 몇 도부터 온열질환이 급증하나 | 1도 구간별 하루 평균 환자 수 |
| `a3_payout_hours.py` | 지역별 연간 지급 구간 시간과 예산 | 평균 해·더운 해 시간, 예산표 |
| `a4_warning_vs_grid.py` | 특보 기준이 놓치는 위험 시간 | 지역별 보장 공백 막대 |
| `a5_road_heat.py` | 도로 위는 공식 체감온도보다 몇 도 높나 | 시각별 차이 곡선, 알림 보정폭 |
| `model_heat_risk.py` | 온열질환 위험 예측, 지급 기준 근거 | 모델 성능표, 31도 대비 위험 2·5·10배 온도 |

각 스크립트는 `# %%` 셀로 나뉘어 있어 VS Code나 Jupyter에서 셀 단위로 실행할 수 있다.

### 초안 값 (분석 후 확정)

- 35도 이상: 14~17시에 쉬면 보전 / 38도 이상: 모든 시간 보전 / 33도 이상: 알림만
- 시간당 17,210원 (제주 기후보험 기준점), 하루 최대 4시간, 한 달 최대 40시간

### 다음 단계

1. 실제 데이터 받기: 기상청 인증키, 격자-행정구역 표, 무더위쉼터 목록 → `data/raw/`
2. 분석 1~5를 실제 데이터로 다시 돌려 지급 기준(35·38도, 시간대) 확정 → `engine/rules.py`의 `RULES`만 고치면 앱 전체에 반영
3. 쉼터 밖 쉼의 위치 정지 확인 (일정 간격으로 위치를 받아 이동 거리 비교)
4. 2026년 여름 실제 기상으로 가상 라이더 시뮬레이션 → 지자체별 예산 추정
