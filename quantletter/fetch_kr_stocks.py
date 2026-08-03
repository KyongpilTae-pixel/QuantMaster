# -*- coding: utf-8 -*-
"""한국 주식 유니버스 데이터 다운로드 (yfinance KS 접미사).

처음 한 번 실행하면 kr_stocks_5yr.csv 를 생성합니다.
fetch_sample_data.py 와 같은 포맷 (date, Name, close long-format).

사용
  python fetch_kr_stocks.py
"""
import sys
from datetime import datetime, timedelta

import pandas as pd

STOCK_START = (datetime.today() - timedelta(days=365 * 6 + 10)).strftime("%Y-%m-%d")  # 6년치 → 12m룩백 후 5년 백테스트
END         = datetime.today().strftime("%Y-%m-%d")

# 40 major KOSPI stocks (시가총액 상위, 섹터 분산)
KR_UNIVERSE = {
    # 반도체/IT
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "009150": "삼성전기",
    "066570": "LG전자",
    "035420": "NAVER",
    "035720": "카카오",
    "036570": "엔씨소프트",
    # 2차전지/에너지
    "373220": "LG에너지솔루션",
    "006400": "삼성SDI",
    "051910": "LG화학",
    "096770": "SK이노베이션",
    "010950": "S-Oil",
    "015760": "한국전력",
    # 바이오/헬스케어
    "207940": "삼성바이오로직스",
    "068270": "셀트리온",
    "000100": "유한양행",
    # 자동차/방산
    "005380": "현대차",
    "000270": "기아",
    "086280": "현대글로비스",
    "004020": "현대제철",
    "012450": "한화에어로스페이스",
    "047810": "한국항공우주",
    # 금융
    "105560": "KB금융",
    "055550": "신한지주",
    "086790": "하나금융지주",
    "316140": "우리금융지주",
    "032830": "삼성생명",
    "000810": "삼성화재",
    "024110": "기업은행",
    # 통신
    "017670": "SK텔레콤",
    "032640": "LG유플러스",
    "030200": "KT",
    # 소비재/유통
    "097950": "CJ제일제당",
    "033780": "KT&G",
    "028260": "삼성물산",
    "003550": "LG",
    # 조선/항공
    "009540": "HD한국조선해양",
    "042660": "한화오션",
    "003490": "대한항공",
    # 소재
    "010130": "고려아연",
}


def fetch_kr_stocks():
    try:
        import yfinance as yf
    except ImportError:
        print("[Error] yfinance not installed: pip install yfinance")
        sys.exit(1)

    print(f"Downloading {len(KR_UNIVERSE)} KR stocks ({STOCK_START} ~ {END})...\n")
    all_data = []
    failed   = []

    for code, name in KR_UNIVERSE.items():
        ticker = f"{code}.KS"
        try:
            tk  = yf.Ticker(ticker)
            df  = tk.history(start=STOCK_START, end=END, auto_adjust=True)
            if df.empty or len(df) < 50:
                raise ValueError("too few rows")
            df  = df[["Close"]].rename(columns={"Close": "close"})
            df.index = df.index.tz_localize(None)
            df["Name"] = code          # use code as Name (pipeline uses code for FDR)
            df.index.name = "date"
            df = df.reset_index()[["date", "Name", "close"]]
            all_data.append(df)
            print(f"  {code} {name}: {len(df)} rows")
        except Exception as e:
            print(f"  {code} {name}: FAILED - {e}")
            failed.append(code)

    if not all_data:
        print("\nFATAL: no data downloaded")
        sys.exit(1)

    combined = pd.concat(all_data, ignore_index=True)
    combined.to_csv("kr_stocks_5yr.csv", index=False, encoding="utf-8")
    print(f"\nOK: kr_stocks_5yr.csv ({len(combined)} rows, {len(all_data)} stocks)")

    if failed:
        print(f"Failed stocks ({len(failed)}): {failed}")

    # Save code->name mapping
    import json
    mapping = {code: name for code, name in KR_UNIVERSE.items() if code not in failed}
    with open("kr_names.json", "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=1)
    print("OK: kr_names.json saved")


if __name__ == "__main__":
    fetch_kr_stocks()
