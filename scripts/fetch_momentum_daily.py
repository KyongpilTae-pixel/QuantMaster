"""매일 장 마감 후 KOSPI/KOSDAQ/SP500 기간 모멘텀을 자동 수집해 캐시에 저장.

실행 시점 권장: 16:00 KST (한국 시장 마감 30분 후)
Windows 작업 스케줄러에 등록해 매일 자동 실행.

등록 예시:
  schtasks /create /tn "QuantMaster 기간모멘텀" /tr
    "C:\\miniconda3\\envs\\quantmaster\\python.exe
     C:\\project\\quant\\scripts\\fetch_momentum_daily.py"
  /sc daily /st 16:00 /ru SYSTEM
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.stock_scanner import (
    scan_stock_momentum_all_periods,
    save_momentum_cache_all,
    load_momentum_cache_all,
)


def main():
    today = datetime.today().strftime("%Y-%m-%d")
    print(f"[{today}] 기간 모멘텀 일별 수집 시작", flush=True)

    markets = ["KOSPI", "KOSDAQ", "SP500"]

    for market in markets:
        existing = load_momentum_cache_all(market)
        if existing:
            print(f"[{market}] 오늘 캐시 이미 존재 ({len(existing)}종목) — 건너뜀", flush=True)
            continue

        print(f"[{market}] 스캔 시작 (유니버스 150종목, 최대 90초)...", flush=True)
        try:
            def _progress(cur, tot, _mkt=market):
                if cur % 20 == 0 or cur == tot:
                    print(f"[{_mkt}] {cur}/{tot}개 처리 중...", flush=True)

            data = scan_stock_momentum_all_periods(
                market=market,
                min_mktcap_eok=1_000,
                top_n=30,
                max_universe=150,
                _timeout_s=90,
                progress_fn=_progress,
            )

            if data:
                save_momentum_cache_all(market, data)
                warn = getattr(data, "warning", "")
                print(f"[{market}] {len(data)}종목 캐시 저장 완료" +
                      (f"  ⚠ {warn}" if warn else ""), flush=True)
            else:
                print(f"[{market}] 결과 없음 (빈 ScanResults)", flush=True)

        except Exception as e:
            print(f"[{market}] 오류: {e}", flush=True)

    print(f"[{today}] 완료", flush=True)


if __name__ == "__main__":
    main()
