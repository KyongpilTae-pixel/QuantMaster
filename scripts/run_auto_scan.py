"""퀀트 + 눌림목 스캔 자동화 스크립트.

KOSPI · KOSDAQ · SP500 에 대해 퀀트/눌림목 스캔을 실행하고
결과를 tracked_picks DB에 저장한다.

권장 실행 시점:
  08:30 KST — 장 시작 전 준비 (전일 종가 기준)
  16:10 KST — 장 마감 후 (당일 종가 기준)

Task Scheduler 등록 예시 (관리자 권한 PowerShell):
  $py = "C:\\miniconda3\\envs\\quantmaster\\python.exe"
  $script = "C:\\project\\quant\\scripts\\run_auto_scan.py"

  # 08:30
  schtasks /create /tn "QuantMaster 자동스캔(오전)" `
    /tr "$py $script" /sc daily /st 08:30 /ru SYSTEM /f

  # 16:10
  schtasks /create /tn "QuantMaster 자동스캔(오후)" `
    /tr "$py $script" /sc daily /st 16:10 /ru SYSTEM /f
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.scan_results_tracker import save_scan_picks

MARKETS  = ["KOSPI", "KOSDAQ", "SP500"]
TOP_N    = 30
MAX_UNI  = 150
TIMEOUT  = 90


def _run_quant(market: str) -> int:
    """퀀트 스캔 실행 → tracked_picks 저장. 반환: 저장 건수."""
    try:
        from scanner import QuantScanner
        mkt_map = {"SP500": "SP500", "KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}
        scanner  = QuantScanner(market=mkt_map[market])
        results  = scanner.scan()
        items    = list(results) if results else []
        if not items:
            print(f"  [{market}] 퀀트 — 결과 없음", flush=True)
            return 0
        n = save_scan_picks("quant", market, items)
        warn = getattr(results, "warning", "")
        print(f"  [{market}] 퀀트 — {len(items)}건 스캔 / {n}건 신규 저장"
              + (f"  ⚠ {warn}" if warn else ""), flush=True)
        return n
    except Exception as e:
        print(f"  [{market}] 퀀트 오류: {e}", flush=True)
        return 0


def _run_pullback(market: str) -> int:
    """눌림목 스캔 실행 → tracked_picks 저장. 반환: 저장 건수."""
    try:
        from utils.pullback_scanner import scan_pullback_stocks
        mkt_map = {"SP500": "SP500", "KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}
        results = scan_pullback_stocks(
            market=mkt_map[market],
            min_mktcap_eok=3_000 if market != "SP500" else 0,
            min_dip_1w=-5.0,
            max_rsi=45.0,
            min_trend_3m=0.0,
            top_n=TOP_N,
            max_universe=MAX_UNI,
            _timeout_s=TIMEOUT,
        )
        items = list(results) if results else []
        if not items:
            print(f"  [{market}] 눌림목 — 결과 없음", flush=True)
            return 0
        n = save_scan_picks("pullback", market, items)
        warn = getattr(results, "warning", "")
        print(f"  [{market}] 눌림목 — {len(items)}건 스캔 / {n}건 신규 저장"
              + (f"  ⚠ {warn}" if warn else ""), flush=True)
        return n
    except Exception as e:
        print(f"  [{market}] 눌림목 오류: {e}", flush=True)
        return 0


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{now}] 자동 스캔 시작 (퀀트 + 눌림목 / {', '.join(MARKETS)})", flush=True)

    total = 0
    for market in MARKETS:
        print(f"\n[{market}]", flush=True)
        total += _run_quant(market)
        total += _run_pullback(market)

    print(f"\n[완료] 총 {total}건 신규 저장", flush=True)


if __name__ == "__main__":
    main()
