"""매일 11:00 KST에 KOSPI/KOSDAQ 당일 주도주를 자동으로 조회해 캐시 저장."""

import sys
import os

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.data_loader import fetch_leaders_combined, save_leaders_cache


def main():
    for market in ("KOSPI", "KOSDAQ"):
        print(f"[{market}] 당일 주도주 조회 중...", flush=True)
        try:
            data = fetch_leaders_combined(market, top_n=30)
            save_leaders_cache(market, data)
            print(f"[{market}] {len(data)}건 캐시 저장 완료", flush=True)
        except Exception as e:
            print(f"[{market}] 오류: {e}", flush=True)


if __name__ == "__main__":
    main()
