"""회의록 11/7 기준: 시간대별 활동일 (5개 시간대, 그 시간대에 1시간 이상 운행한 날)
운행 시간 = 그날 첫 콜 수락 ~ 마지막 배달 완료 (식사 등 30분 넘는 공백은 뺌)"""
import pandas as pd, numpy as np
BANDS=[('아침',6,9),('오전',9,12),('낮',12,15),('오후',15,18),('밤',18,22)]
def band_of(m):
    h=m/60
    for i,(n,a,b) in enumerate(BANDS):
        if a<=h<b: return i
    return -1
import sys
YEAR=int(sys.argv[1]) if len(sys.argv)>1 else 2025
for tag in (sys.argv[2:] if len(sys.argv)>2 else ['']):
    C=pd.read_csv(f'/home/claude/sim/out/가상라이더_관악_콜_{YEAR}{tag}.csv.gz',usecols=['라이더ID','날짜','수락시각','배달완료'])
    for c in ['수락시각','배달완료']: C[c]=pd.to_datetime(C[c])
    C['날짜']=pd.to_datetime(C['날짜'])
    C['s']=(C['수락시각']-C['날짜']).dt.total_seconds()/60; C['e']=(C['배달완료']-C['날짜']).dt.total_seconds()/60
    C=C.sort_values(['라이더ID','날짜','s'])
    # 근무 구간: 다음 수락까지 공백 30분 이하면 이어 붙임
    C['gap']=C.groupby(['라이더ID','날짜'])['s'].shift(-1)-C['e']
    rows=[]
    for (rid,d),g in C.groupby(['라이더ID','날짜'],sort=False):
        s,e,gp=g['s'].values,g['e'].values,g['gap'].values
        segs=[]; cs=s[0]
        for i in range(len(s)):
            if np.isnan(gp[i]) or gp[i]>30: segs.append((cs,e[i])); 
            if not np.isnan(gp[i]) and gp[i]>30: cs=s[i+1]
        mins=[0]*5
        for a,b in segs:
            for k,(n,lo,hi) in enumerate(BANDS):
                mins[k]+=max(0,min(b,hi*60)-max(a,lo*60))
        rows.append((rid,d,*[m>=60 for m in mins]))
    A=pd.DataFrame(rows,columns=['라이더ID','날짜']+[b[0] for b in BANDS])
    A.to_pickle(f'active_{YEAR}{tag}.pkl'); print(tag,'rider-days',len(A),flush=True)
