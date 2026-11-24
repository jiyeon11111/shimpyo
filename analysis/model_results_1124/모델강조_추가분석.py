# 기획서 4장 보강용 추가 분석 — 코랩 새 런타임에서 이 칸만 실행 (모델 재학습 없음, 약 10~15분)
# 순서: 2026 비교 → 변수 중요도(SHAP이 가장 느림)
# 1) 최종모델(차이_보정, 2021~2025 재학습)의 변수 중요도: LightGBM gain + SHAP 평균 절댓값
# 2) 2026 시험: 관측소 / 단순 보정(가까운 관측소 + 시간대별 평균 편차) / AI 비교
#    조건은 pipeline.py 6장과 같음: 같은 전처리, 정답 = 보정 정답(센서 측정 편차 제거) 33℃ 이상
# 출력(모델결과 폴더): 변수중요도_최종모델.csv, 단순보정비교_2026.csv, 단순보정비교_2026_관악동별.csv, 단순보정_시간별편차.csv
import os, sys, unicodedata, time
import numpy as np, pandas as pd, lightgbm as lgb

nfc = lambda s: unicodedata.normalize('NFC', s)
YEARS_DEV, TEST_YEAR, HOT, PAY_LINE, SEED = [2021, 2022, 2023, 2024, 2025], 2026, 33.0, 32.0, 42
NEED = [f'학습표_{y}.csv.gz' for y in YEARS_DEV + [TEST_YEAR]] + ['센서_특징표.csv', '최종모델_차이_보정.txt', '측정편차_시간별.csv']

if 'google.colab' in sys.modules:
    from google.colab import drive
    drive.mount('/content/drive')
    roots = ('/content/drive/MyDrive', '/content/drive/Shareddrives', '/content/drive/.shortcut-targets-by-id')
else:                                    # 로컬 동작 확인용: SHIMPYO_DATA 폴더에서 찾음
    roots = (os.environ.get('SHIMPYO_DATA', 'data'),)
P = {}
for root in roots:
    for r, ds, fs in os.walk(root):
        for f in fs:
            if nfc(f) in NEED and nfc(f) not in P:
                P[nfc(f)] = os.path.join(r, f)
miss = [n for n in NEED if n not in P]
if miss and 'google.colab' in sys.modules:
    raise SystemExit(f'못 찾은 파일: {miss}  → 드라이브 웹에서 공모전 폴더를 "내 드라이브에 바로가기 추가" 후 다시 실행')
YEARS_DEV = [y for y in YEARS_DEV if f'학습표_{y}.csv.gz' in P]
OUT = os.path.dirname(P['최종모델_차이_보정.txt']) if '최종모델_차이_보정.txt' in P else 'out'
print('결과 폴더:', OUT, '| 개발 연도:', YEARS_DEV)

# ---------- pipeline.py와 같은 전처리 ----------
TIME_COLS = [f'aws{k}_{v}' for k in (1, 2, 3) for v in ('거리m', '기온', '습도', '풍속', '체감온도')] + \
            ['asos_기온', 'asos_습도', 'asos_풍속', 'asos_체감온도']
READ_COLS = ['연도', '시각', '시리얼', '자치구', '행정동', '행정동코드', '체감온도', '기온', '습도', '기준선_체감온도',
             '월', '시', '요일', '연중일'] + TIME_COLS


def load_year(y):
    df = pd.read_csv(P[f'학습표_{y}.csv.gz'], usecols=READ_COLS, dtype={'시리얼': str, '행정동코드': str})
    for c in df.select_dtypes('float64'):
        df[c] = df[c].astype('float32')
    for c in ('월', '시', '요일', '연중일'):
        df[c] = df[c].astype('int16')
    bad = (df['기온'] <= 5) | (df['기온'] >= 45)
    df = df.sort_values(['시리얼', '시각'], ignore_index=True)
    same = (df['시리얼'].values[1:] == df['시리얼'].values[:-1]) & \
           (df['기온'].values[1:] == df['기온'].values[:-1]) & (df['습도'].values[1:] == df['습도'].values[:-1])
    same = pd.Series(np.r_[False, same])
    stuck = same.groupby((~same).cumsum()).cumsum() >= 6
    spike = (df['체감온도'] - df[['aws1_체감온도', 'aws2_체감온도', 'aws3_체감온도']].mean(axis=1)).abs() >= 10
    return df[~(bad | stuck | spike)].drop(columns=['시각']).reset_index(drop=True)


SENS = pd.read_csv(P['센서_특징표.csv'], dtype={'시리얼': str, '행정동코드': str})
PLACE_COLS = [c for c in SENS.columns if c.startswith(('피복_', '건물비율', '평균층수', '용적지수', '도로면비율',
                                                       '도로밀도', '대로밀도', '최근접'))] + ['위도', '경도']
_PLACE = SENS.set_index('시리얼')[PLACE_COLS].astype('float32')


def join_place(df):
    place = _PLACE.reindex(df['시리얼'].values)
    place.index = df.index
    return pd.concat([df, place], axis=1)


off = pd.read_csv(P['측정편차_시간별.csv']) if '측정편차_시간별.csv' in P else pd.read_csv('out/측정편차_시간별.csv')
OFFSET = off.set_index('시')['편차'].reindex(range(24)).interpolate().bfill().ffill()
y_cor = lambda df: df['체감온도'].values.astype('float64') - OFFSET.reindex(df['시']).values   # 보정 정답

# ---------- 변수 한글 설명 ----------
ORD = {'1': '가장 가까운', '2': '두 번째로 가까운', '3': '세 번째로 가까운'}
VAR = {'기온': '기온', '습도': '습도', '풍속': '풍속', '체감온도': '체감온도', '거리m': '까지 거리(m)'}
COVER = {'나무': '나무', '초지': '풀밭', '농경지': '농경지', '시가지': '시가지(건물·포장면)', '나지': '맨땅', '물': '물'}


def describe(c):
    if c.startswith('aws'):
        k, v = c[3], c.split('_', 1)[1]
        return f'{ORD[k]} AWS{VAR[v]}' if v == '거리m' else f'{ORD[k]} AWS {VAR[v]}'
    if c.startswith('asos_'):
        return f'서울 종관관측소(ASOS) {VAR[c[5:]]}'
    if c.startswith('피복_'):
        _, kind, r = c.split('_')
        return f'반경 {r} 안 {COVER[kind]} 면적 비율(위성 토지피복)'
    fixed = {'기준선_체감온도': '가장 가까운 AWS 체감온도(기준선, 모델은 이 값과의 차이를 예측)',
             '월': '월', '시': '시각(0~23시)', '요일': '요일', '연중일': '1년 중 몇 번째 날',
             '최근접도로_m': '가장 가까운 도로까지 거리(m)', '최근접대로_m': '가장 가까운 큰길까지 거리(m)',
             '위도': '센서 위도', '경도': '센서 경도'}
    if c in fixed:
        return fixed[c]
    name, r = c.rsplit('_', 1)
    base = {'건물비율': '건물이 덮은 면적 비율', '평균층수': '건물 평균 층수', '용적지수': '건물 연면적 지수(높고 빽빽할수록 큼)',
            '도로면비율': '도로 면적 비율', '도로밀도': '도로 길이 밀도', '대로밀도': '큰길 길이 밀도'}[name]
    return f'반경 {r} 안 {base}'


# ---------- 1. 모델 불러오기 ----------
m = lgb.Booster(model_str=open(P['최종모델_차이_보정.txt'], encoding='utf-8').read()) if '최종모델_차이_보정.txt' in P \
    else lgb.Booster(model_str=open(os.environ['SHIMPYO_MODEL'], encoding='utf-8').read())
FEATS = m.feature_name()
print('모델 입력', len(FEATS), '개, 트리', m.num_trees(), '개')

# ---------- 2. 개발 연도 돌며: 단순 보정 편차(시간대별 평균) + SHAP 표본 ----------
s_sum, s_cnt, shap_parts = np.zeros(24), np.zeros(24), []
rng = np.random.default_rng(SEED)
for y in YEARS_DEV:
    t = time.time()
    df = load_year(y)
    d = y_cor(df) - df['기준선_체감온도'].values
    ok = ~np.isnan(d)
    h = df['시'].values[ok]
    s_sum += np.bincount(h, d[ok], 24)
    s_cnt += np.bincount(h, minlength=24)
    pick = df[df['기준선_체감온도'].notna()].sample(n=min(1000, ok.sum()), random_state=SEED + y)
    shap_parts.append(join_place(pick)[FEATS])
    print(y, f'{len(df):,}행', f'{time.time() - t:.0f}초', flush=True)
    del df
BIAS = pd.Series(s_sum / s_cnt, index=range(24))
pd.DataFrame({'시': BIAS.index, '평균편차(보정정답-가까운관측소)': BIAS.round(3).values, '행수': s_cnt.astype(int)}) \
    .to_csv(f'{OUT}/단순보정_시간별편차.csv', index=False, encoding='utf-8-sig')


# ---------- 3. 2026 시험 ----------
if f'학습표_{TEST_YEAR}.csv.gz' in P:
    test = join_place(load_year(TEST_YEAR))
    y = y_cor(test)
    base = test['기준선_체감온도'].values.astype('float64')
    simple = base + BIAS.reindex(test['시']).values
    ai = m.predict(test[FEATS]) + base
    keep = ~(np.isnan(y) | np.isnan(base))                 # 세 방법 모두 같은 행에서 비교


    def score(mask, label):
        rows = []
        yy = y[mask]
        pos, neg = yy >= HOT, yy < HOT
        for name, p in (('관측소(가까운 AWS)', base), ('단순 보정', simple), ('AI(차이_보정)', ai)):
            pp = p[mask]
            e = pp - yy
            for line in (HOT, PAY_LINE):
                rows.append({'범위': label, '방법': name, '판정선': line, '행': int(mask.sum()), '정답33이상': int(pos.sum()),
                             'MAE': round(np.abs(e).mean(), 3), 'RMSE': round(np.sqrt((e ** 2).mean()), 3),
                             '치우침': round(e.mean(), 3),
                             '미탐지율': round(((pp < line) & pos).sum() / max(pos.sum(), 1), 4),
                             '오탐지율': round(((pp >= line) & neg).sum() / max(neg.sum(), 1), 4)})
        return rows

    gw = test['자치구'].astype(str).values == '관악구'
    res = pd.DataFrame(score(keep, '서울 센서 지점 전체') + score(keep & gw, '관악구 센서 지점'))
    res.to_csv(f'{OUT}/단순보정비교_2026.csv', index=False, encoding='utf-8-sig')
    print(res.to_string(index=False))
    chk = res[(res['범위'] == '서울 센서 지점 전체')].set_index(['방법', '판정선'])['미탐지율']
    print('\n[4장 표와 같은지 확인] 관측소 33℃ 미탐지', chk[('관측소(가까운 AWS)', 33.0)], '(4장 0.4285) | AI 32℃',
          chk[('AI(차이_보정)', 32.0)], '(4장 0.082)')

    dong = []
    for (code, nm), idx in test[keep & gw].groupby(['행정동코드', '행정동']).groups.items():
        mk = np.zeros(len(test), bool)
        mk[idx] = True
        for r in score(mk, nm):
            if r['판정선'] == PAY_LINE:
                dong.append({'행정동코드': code, **r, '센서수': test.loc[idx, '시리얼'].nunique()})
    dong = pd.DataFrame(dong)
    dong.to_csv(f'{OUT}/단순보정비교_2026_관악동별.csv', index=False, encoding='utf-8-sig')
    print(f'\n관악구 행정동 {dong["범위"].nunique()}곳 (센서가 있는 동만)')
# ---------- 4. 변수 중요도 (SHAP은 느려서 맨 마지막) ----------
print('SHAP 계산 중 (5천 행, 수 분)...', flush=True)
X = pd.concat(shap_parts, ignore_index=True)
contrib = m.predict(X, pred_contrib=True, num_threads=os.cpu_count())[:, :-1]          # 마지막 열은 기댓값
gain = m.feature_importance('gain')
imp = pd.DataFrame({'변수': FEATS, '한글 설명': [describe(c) for c in FEATS],
                    'gain': gain.round(1), 'gain_비율': (gain / gain.sum()).round(4),
                    'SHAP_평균절댓값(℃)': np.abs(contrib).mean(0).round(4)})
imp['SHAP_비율'] = (imp['SHAP_평균절댓값(℃)'] / imp['SHAP_평균절댓값(℃)'].sum()).round(4)
imp = imp.sort_values('gain', ascending=False).reset_index(drop=True)
imp.insert(0, '순위(gain)', imp.index + 1)
imp['순위(SHAP)'] = imp['SHAP_평균절댓값(℃)'].rank(ascending=False, method='min').astype(int)
imp.to_csv(f'{OUT}/변수중요도_최종모델.csv', index=False, encoding='utf-8-sig')
print(imp.head(15).to_string(index=False))
del X, contrib
print('끝. 결과 폴더:', OUT)
