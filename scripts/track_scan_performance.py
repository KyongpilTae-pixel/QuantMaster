"""스캔 성과 추적 — 매일 현재가 업데이트 스크립트.

tracked_picks 테이블의 활성 종목(≤30거래일)에 대해
오늘 현재가를 조회해 tracked_prices 에 저장한다.

권장 실행 시점: 16:20 KST (장 마감 후 데이터 확정 시점)

Task Scheduler 등록 예시:
  $py = "C:\\miniconda3\\envs\\quantmaster\\python.exe"
  $script = "C:\\project\\quant\\scripts\\track_scan_performance.py"
  schtasks /create /tn "QuantMaster 성과추적" `
    /tr "$py $script" /sc daily /st 16:20 /ru SYSTEM /f
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.scan_results_tracker import update_pick_prices, load_tracked_picks, get_tracker_summary


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{now}] 성과 추적 업데이트 시작", flush=True)

    try:
        updated = update_pick_prices()
        print(f"  가격 업데이트: {updated}건", flush=True)
    except Exception as e:
        print(f"  가격 업데이트 오류: {e}", flush=True)
        updated = 0

    # 요약 출력
    try:
        picks   = load_tracked_picks(days=30)
        summary = get_tracker_summary(picks)
        print(f"\n  [요약] 총 추적 {summary['total']}종목 / "
              f"데이터 있음 {summary['tracked']}건 / "
              f"승률 {summary['win_rate_str']} / "
              f"평균수익 {summary['avg_ret_str']}", flush=True)
        if summary.get("best_ret") is not None:
            print(f"  최고: {summary['best_str']}", flush=True)
            print(f"  최저: {summary['worst_str']}", flush=True)
    except Exception as e:
        print(f"  요약 출력 오류: {e}", flush=True)

    print(f"[완료]", flush=True)


if __name__ == "__main__":
    main()
