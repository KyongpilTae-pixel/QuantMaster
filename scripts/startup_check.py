"""
QuantMaster Pro — 서버 시작 전 탭별 상태 점검.

실행:
    python scripts/startup_check.py            # 점검만
    python scripts/startup_check.py --start    # 점검 후 reflex 서버 자동 실행
"""

import sys
import os
import time
import subprocess
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PYTHON = sys.executable
REFLEX_CMD = [PYTHON, "-m", "reflex", "run", "--backend-port", "7500"]

_PASS = "✓"
_FAIL = "✗"
_WARN = "△"


def _check(label: str, fn, warn_only: bool = False):
    start = time.time()
    try:
        fn()
        elapsed = time.time() - start
        print(f"  {_PASS}  {label:<40} ({elapsed:.1f}s)")
        return True
    except Exception as e:
        elapsed = time.time() - start
        mark = _WARN if warn_only else _FAIL
        print(f"  {mark}  {label:<40} ({elapsed:.1f}s)  → {e}")
        return warn_only  # warn_only면 실패로 집계하지 않음


def check_db():
    """포트폴리오/히스토리 탭 — SQLite DB 접근"""
    from utils.scan_db import load_holdings, load_run_list
    load_holdings()
    load_run_list()


def check_naver_api():
    """종목조회/당일주도주 탭 — NAVER 펀더멘털 API"""
    from utils.data_loader import _fetch_kr_naver_fundamentals
    result = _fetch_kr_naver_fundamentals("005930")
    if result is None:
        raise RuntimeError("NAVER API 응답 없음")


def check_kr_listing():
    """스캐너/하락방어 탭 — KR 종목 목록 (fdr 404 fallback 포함)"""
    from utils.data_loader import fetch_kr_stock_listing
    df = fetch_kr_stock_listing("KOSPI", min_mktcap_eok=50_000)
    if df is None:
        raise RuntimeError("KR 종목 목록 조회 실패")


def check_symbol_search():
    """종목조회 탭 — 코드/이름 검색"""
    from utils.data_loader import _search_kr_symbol
    code, market = _search_kr_symbol("005930")
    if not code:
        raise RuntimeError("삼성전자(005930) 코드 조회 실패")


def check_ohlcv():
    """분석 탭 — OHLCV 데이터 수신"""
    import FinanceDataReader as fdr
    from datetime import datetime, timedelta
    end = datetime.today()
    start = end - timedelta(days=30)
    df = fdr.DataReader("005930", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    if df.empty:
        raise RuntimeError("OHLCV 데이터 없음")


def check_momentum():
    """시장모멘텀 탭 — momentum_scanner 데이터 수집"""
    from utils.momentum_scanner import fetch_momentum_data
    result = fetch_momentum_data()
    if not result.get("rows"):
        raise RuntimeError("모멘텀 데이터 rows 없음")
    if result.get("error"):
        raise RuntimeError(result["error"])


def check_leaders_kr():
    """당일주도주 탭 — KR 주도주 (KOSPI 소규모)"""
    from utils.data_loader import fetch_leaders_combined
    data = fetch_leaders_combined("KOSPI", top_n=5)
    if not data:
        raise RuntimeError("KOSPI 주도주 데이터 없음")
    required_flags = ["is_etf", "is_near_high", "has_vol_rank", "has_rise_rank",
                      "change_positive", "has_score_b", "is_us"]
    for flag in required_flags:
        if flag not in data[0]:
            raise RuntimeError(f"bool 플래그 '{flag}' 누락")


def check_leaders_us():
    """당일주도주 탭 — US 주도주 (소규모)"""
    from utils.data_loader import fetch_leaders_combined
    data = fetch_leaders_combined("US", top_n=3)
    if not data:
        raise RuntimeError("US 주도주 데이터 없음")


def run_checks() -> bool:
    print("\n" + "=" * 60)
    print("  QuantMaster Pro — 탭별 시작 전 점검")
    print("=" * 60)

    results = []

    print("\n[ DB / 로컬 ]")
    results.append(_check("포트폴리오·히스토리 탭 (SQLite DB)", check_db))

    print("\n[ 네트워크 — 한국 ]")
    results.append(_check("NAVER 펀더멘털 API",          check_naver_api))
    results.append(_check("KR 종목 목록 (fdr+fallback)", check_kr_listing))
    results.append(_check("종목 코드·이름 검색",          check_symbol_search))
    results.append(_check("OHLCV (분석 탭)",             check_ohlcv))
    results.append(_check("당일주도주 KR (KOSPI 5건)",   check_leaders_kr))

    print("\n[ 네트워크 — 글로벌 ]")
    results.append(_check("시장모멘텀 (6개 자산)",        check_momentum))
    results.append(_check("당일주도주 US (3건)", check_leaders_us, warn_only=True))

    passed = sum(results)
    total  = len(results)
    failed = total - passed

    print("\n" + "-" * 60)
    if failed == 0:
        print(f"  결과: 전체 통과 ({passed}/{total})")
    else:
        print(f"  결과: {passed}/{total} 통과  ({failed}건 실패)")
    print("=" * 60 + "\n")

    return failed == 0


def main():
    parser = argparse.ArgumentParser(description="QuantMaster 시작 전 점검")
    parser.add_argument("--start", action="store_true",
                        help="점검 후 reflex 서버 자동 실행")
    parser.add_argument("--force", action="store_true",
                        help="점검 실패해도 서버 시작")
    args = parser.parse_args()

    ok = run_checks()

    if args.start:
        if ok or args.force:
            print("서버를 시작합니다...\n")
            os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            os.execv(PYTHON, REFLEX_CMD)
        else:
            print("점검 실패 항목이 있습니다. --force 옵션으로 강제 시작할 수 있습니다.")
            sys.exit(1)


if __name__ == "__main__":
    main()
