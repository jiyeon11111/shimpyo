"""분석 1~5와 위험 예측 모델을 차례로 실행한다. 하나가 실패해도 나머지는 계속 돈다."""
import os
import runpy
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SCRIPTS = ["a1_delivery_vs_heat.py", "a2_threshold.py", "a3_payout_hours.py",
           "a4_warning_vs_grid.py", "a5_road_heat.py", "model_heat_risk.py"]

failed = []
for s in SCRIPTS:
    print(f"\n===== {s} =====")
    try:
        runpy.run_path(os.path.join(HERE, s), run_name="__main__")
    except Exception:
        traceback.print_exc()
        failed.append(s)
print("\n완료." if not failed else f"\n실패: {failed}")
