"""분석 3·4: 가상 라이더(관악구)로 N분, 하루 지급 횟수, 금액 상한, 예산 정하기

판정 규칙 (팀 합의안, engine/rules.py · payout.py와 같은 정의)
  1. 최근 4주 같은 요일·같은 시간대에 운행한 주가 WEEKS_K주 이상
  2. 최근 60분 동안 가장 오래 달린 동의 체감온도(실측, 관악_동별체감온도) 33도 이상
  3. 최근 2시간 실제 배달 이동(음식점까지 + 고객까지) 누적 N분 이상, 20분 넘는 공백이면 0으로
  4. 쉬기 시작 → 30분 쉼 가정 → 평소 시간당 수입 × 30/60 지급. 쉬면 노출 0으로
쉬기 버튼을 누를 수 있는 순간 = 배달을 마친 직후 (가상 로그에는 버튼 행동이 없으므로)
행동 가정: 자격이 되면 확률 P로 쉰다 (1.0 / 0.5 / 0.25)
"""
import sys, glob, json
import numpy as np, pandas as pd
sys.path.insert(0, '/home/claude/repo/shimpyo')
from engine.rules import exposure_min
from datetime import datetime, timedelta

OUT = '/home/claude/sim/a3'
REST_MIN, PAY_MIN, GAP = 30, 30, 20


def load(year, tag=''):
    C = pd.read_csv(f'/home/claude/sim/out/가상라이더_관악_콜_{year}{tag}.csv.gz',
                    dtype={'출발동코드': str, '음식점동코드': str, '고객동코드': str})
    for c in ['수락시각', '음식점도착', '픽업시각', '배달완료']:
        C[c] = pd.to_datetime(C[c]).astype('datetime64[ns]')
    C['날짜'] = pd.to_datetime(C['날짜']).astype('datetime64[ns]')
    T = pd.read_csv(f'{OUT}/관악_동별체감온도_{year}.csv.gz', dtype={'행정동코드': str}, parse_dates=['시각'])
    P = T.pivot(index='시각', columns='행정동코드', values='체감온도')
    return C, P


def slot_table(C):
    """라이더 × 날짜 × 시(수락 기준) → 그 시간 수입, 일했는지"""
    C = C.assign(h=C['수락시각'].dt.hour, d=C['날짜'].map(lambda x: x.toordinal()))
    s = C.groupby(['라이더ID', 'd', 'h'])['배달료'].sum()
    return s


def build_opps(C, P, year):
    """배달을 마친 순간마다 판정 재료를 만든다"""
    S = slot_table(C)
    sd = S.to_dict()
    t0 = P.index[0]; PV = P.values; cols = {c: i for i, c in enumerate(P.columns)}
    start = pd.Timestamp(f'{year}-05-15')
    rows = []
    for (rid, day), g in C.groupby(['라이더ID', '날짜'], sort=False):
        if day < start: continue
        base = day.value; dord = day.toordinal(); dh0 = (day.value - t0.value) / 3.6e12
        m = lambda x: (x.values.astype('int64') - base) / 6e10   # 분
        a, ar, pk, dn = m(g['수락시각']), m(g['음식점도착']), m(g['픽업시각']), m(g['배달완료'])
        fr, sh, cu = g['출발동코드'].values, g['음식점동코드'].values, g['고객동코드'].values
        # 이동 구간 (시작, 끝, 동A, 동B)
        Sx = np.empty(2 * len(g)); Ex = np.empty_like(Sx); DA = np.empty(2 * len(g), object); DB = DA.copy()
        Sx[0::2], Ex[0::2], DA[0::2], DB[0::2] = a, ar, fr, sh
        Sx[1::2], Ex[1::2], DA[1::2], DB[1::2] = pk, dn, sh, cu
        G = np.r_[np.inf, Sx[1:] - Ex[:-1]]                       # 앞 이동과의 공백
        # 일한 시간 사이 공백 (배달완료 → 다음 수락): 연속 근무 판단용
        WG = np.r_[np.inf, a[1:] - dn[:-1]]
        cum = np.r_[0, np.cumsum(Ex - Sx)]                         # 누적 이동 분 (구간 끝 기준)
        first = a[0]
        for j in range(len(g)):
            at = dn[j]; mi = 2 * j + 1
            seg0 = mi - int(np.argmax((G[mi::-1] > GAP))) if (G[:mi + 1] > GAP).any() else 0
            lo = at - 120
            ss, ee = Sx[seg0:mi + 1], Ex[seg0:mi + 1]
            expo = np.clip(np.minimum(ee, at) - np.maximum(ss, lo), 0, None).sum()
            # 최근 60분 가장 오래 달린 동
            w = {}
            for k in range(max(0, mi - 12), mi + 1):
                ov = max(0.0, min(Ex[k], at) - max(Sx[k], at - 60))
                if ov > 0:
                    w[DA[k]] = w.get(DA[k], 0) + ov / 2; w[DB[k]] = w.get(DB[k], 0) + ov / 2
            dong = max(w, key=w.get)
            ki = min(int(dh0 + at // 60) + 1, PV.shape[0] - 1)
            temp = PV[ki, cols[dong]]
            h = int(at // 60)
            wk = [sd.get((rid, dord - 7 * q, h)) for q in (1, 2, 3, 4)]
            worked = [v for v in wk if v is not None]
            usual = (sum(worked) / len(worked)) if worked else 0.0
            # 최근 2시간 연속 근무 (출근 후 2시간 이상, 그 사이 20분 넘는 공백 없음)
            cont = (first <= at - 120) and not ((WG[1:j + 1] > GAP) & (a[1:j + 1] > at - 120)).any()
            rows.append((rid, day, at, expo, cum[mi + 1], dong, temp, len(worked), usual, cont))
    O = pd.DataFrame(rows, columns=['라이더ID', '날짜', '분', '노출분', '누적이동', '동', '체감온도', '운행주수', '평소시급', '연속2시간'])
    return O


def verify(C, O, n=300):
    """엔진(engine/rules.exposure_min)과 같은 값인지 표본 확인"""
    rng = np.random.default_rng(1); bad = 0
    sm = O.sample(n, random_state=1)
    for _, r in sm.iterrows():
        g = C[(C['라이더ID'] == r['라이더ID']) & (C['날짜'] == r['날짜'])]
        mv = [(x.to_pydatetime(), y.to_pydatetime()) for x, y in zip(g['수락시각'], g['음식점도착'])] + \
             [(x.to_pydatetime(), y.to_pydatetime()) for x, y in zip(g['픽업시각'], g['배달완료'])]
        at = (r['날짜'] + pd.Timedelta(minutes=float(r['분']))).to_pydatetime()
        e = exposure_min(mv, at)
        bad += abs(e - int(r['노출분'])) > 1
    return bad


def simulate(O, N, P_rest, weeks_k=3, seed=0):
    """자격이 되면 확률 P_rest로 30분 쉼. 쉬면 노출 0 → 이후 이동만 다시 셈"""
    rng = np.random.default_rng(seed)
    hot = (O['체감온도'].values >= 33) & (O['운행주수'].values >= weeks_k)
    expo, cum, mins = O['노출분'].values, O['누적이동'].values, O['분'].values
    key = (O['라이더ID'].astype(str) + O['날짜'].astype(str)).values
    rest = np.zeros(len(O), bool)
    last_key, reset_cum, rest_end = None, -1e9, -1e9
    draws = rng.random(len(O))
    for i in range(len(O)):
        if key[i] != last_key:
            last_key, reset_cum, rest_end = key[i], -1e9, -1e9
        if not hot[i] or mins[i] < rest_end: continue
        e = min(expo[i], cum[i] - reset_cum) if reset_cum > -1e8 else expo[i]
        if e >= N and draws[i] < P_rest:
            rest[i] = True; rest_end = mins[i] + REST_MIN
            reset_cum = cum[i]          # 쉬는 동안 이폙 없음 → 이후 이동만 노출로 셈
    return rest


def summarize(O, rest, label):
    R = O[rest].copy()
    R['지급액'] = (R['평소시급'] * PAY_MIN / 60).round(-1)
    per_day = R.groupby(['라이더ID', '날짜']).size()
    return R, per_day
