"""매일 11:00 / 15:30 KST에 KOSPI/KOSDAQ 당일 주도주를 자동으로 조회해
캐시 저장 + 일별 리포트(reports/YYYY-MM-DD.md) 업데이트."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.data_loader import (
    fetch_leaders_combined,
    save_leaders_cache,
    compute_consecutive_days,
)
from utils.report_generator import append_to_daily_report


def main():
    for market in ("KOSPI", "KOSDAQ"):
        print(f"[{market}] 당일 주도주 조회 중...", flush=True)
        try:
            data = fetch_leaders_combined(market, top_n=30)
            save_leaders_cache(market, data)
            print(f"[{market}] {len(data)}건 캐시 저장 완료", flush=True)

            # 연속 등장일 계산
            data = compute_consecutive_days(market, data)
            streaks = [d for d in data if d.get("consecutive_days", 1) >= 2]
            if streaks:
                print(f"[{market}] 연속 등장: " +
                      ", ".join(f"{d['name']}({d['consecutive_days']}일)" for d in streaks[:5]),
                      flush=True)

            # 일별 리포트 업데이트
            report_path = append_to_daily_report(market, data)
            print(f"[{market}] 리포트 저장: {report_path}", flush=True)

        except Exception as e:
            print(f"[{market}] 오류: {e}", flush=True)


if __name__ == "__main__":
    main()
