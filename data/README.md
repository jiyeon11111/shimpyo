# 데이터 넣는 방법

받은 원본은 `data/raw/`에 아래 파일 이름으로 저장한다. 열 이름이 다르면
`analysis/common.py` 맨 위의 `COLUMNS` 설정만 고치면 된다. 코드는 건드리지 않는다.

ID는 `쉼표_분석데이터_목록`의 데이터 ID와 같다.

| ID | 파일 이름 | 필요한 열 | 비고 |
|---|---|---|---|
| D01 | `asos_hourly_*.csv` (연도별로 여러 개 가능) | 지점, 일시, 기온(°C), 습도(%) | 기상자료개방포털에서 받은 그대로. 인코딩 cp949도 자동 처리 |
| D02 | `asos_stations.csv` | 지점, 지점명, 위도, 경도, 시도 | 시도 열은 직접 채워야 할 수 있음 (예: 서울, 경기) |
| D05 | `heat_warnings.csv` | 시도, 종류, 시작, 해제 | 종류는 주의보 / 경보 / 중대경보. 시작·해제는 `2026-08-03 11:00` 형식 |
| D07 | `food_delivery_monthly.csv` | 월, 거래액 | 월은 `2026-08`, 거래액은 백만원. KOSIS 표를 이 두 열로 정리 |
| D08 | `riders_by_region.csv` | 시도, 라이더수 | 근로복지공단 배달 직종 산재보험 가입자 수 |
| D09 | `heat_illness_daily.csv` | 날짜, 시도, 환자수 | 시도별이 없으면 시도 칸에 `전국` |
| D16 | `sdot_hourly.csv` | 센서, 일시, 기온, 습도, 위도, 경도, 구역 | 구역에 `도로`가 들어간 센서만 분석 5에 쓴다 |

## 실행 순서

```
pip install pandas numpy matplotlib scikit-learn
python analysis/make_sample_data.py     # 실제 데이터가 없을 때만. 가상 데이터를 data/sample/에 만든다
python analysis/run_all.py              # 분석 1~5와 모델을 모두 실행, 결과는 outputs/
```

`data/raw/`에 실제 파일이 있으면 그 파일을, 없으면 `data/sample/`의 가상 파일을 쓴다.
결과 그래프 제목에 `[가상 데이터]`가 붙어 있으면 아직 실제 데이터가 아니라는 뜻이다.
