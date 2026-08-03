# -*- coding: utf-8 -*-
"""SAMPLE 모드용 데이터 다운로드 스크립트.

처음 한 번 실행하면 quantletter_pipeline.py의 SAMPLE 모드에 필요한 CSV 파일을 생성합니다.

생성 파일
  d_kospi.csv       — KOSPI 종가 (일별, 1996~)
  d_usdkrw.csv      — USD/KRW 환율 (일별, 1996~)
  d_spx.csv         — S&P 500 조정종가 + div=0 (일별, 1996~)
  d_gold.csv        — 금 선물 USD 종가 (일별, 1996~)
  d_bond.csv        — 미국 10년 국채금리 % (일별, 1996~)
  all_stocks_5yr.csv — 미국 대형주 20개 5년 일별 종가 (long format)

사용
  python fetch_sample_data.py
"""
import sys
from datetime import datetime, timedelta

import pandas as pd

START      = "1996-01-01"
END        = datetime.today().strftime("%Y-%m-%d")
STOCK_START = (datetime.today() - timedelta(days=365 * 6 + 10)).strftime("%Y-%m-%d")  # 6년치 → 12m룩백 후 5년 백테스트

US_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META",
    "GOOGL", "AVGO", "TSLA", "JPM", "V",
    "LLY", "UNH", "XOM", "MA", "COST",
    "HD", "NFLX", "AMD", "CRM", "ADBE",
]


def _fdr():
    try:
        import FinanceDataReader as fdr
        return fdr
    except ImportError:
        print("[오류] FinanceDataReader 미설치: pip install finance-datareader")
        sys.exit(1)


def _yf():
    try:
        import yfinance as yf
        return yf
    except ImportError:
        print("[오류] yfinance 미설치: pip install yfinance")
        sys.exit(1)


def fetch_kospi():
    print("[1/6] KOSPI (FDR KS11)...")
    fdr = _fdr()
    df  = fdr.DataReader("KS11", START)
    df  = df[["Close"]].rename(columns={"Close": "kospi"})
    df.index.name = "date"
    df.to_csv("d_kospi.csv")
    print(f"  OK d_kospi.csv ({len(df)} rows, {df.index[0].date()} ~ {df.index[-1].date()})")


def fetch_usdkrw():
    print("[2/6] USD/KRW (yfinance KRW=X)...")
    yf  = _yf()
    tk  = yf.Ticker("KRW=X")
    df  = tk.history(start=START, end=END, auto_adjust=True)
    df  = df[["Close"]].rename(columns={"Close": "usdkrw"})
    df.index = df.index.tz_localize(None)
    df.index.name = "date"
    df.to_csv("d_usdkrw.csv")
    print(f"  OK d_usdkrw.csv ({len(df)} rows)")


def fetch_spx():
    print("[3/6] S&P 500 (yfinance ^GSPC)...")
    yf  = _yf()
    tk  = yf.Ticker("^GSPC")
    df  = tk.history(start=START, end=END, auto_adjust=True)
    df  = df[["Close"]].rename(columns={"Close": "spx"})
    df["div"] = 0.0
    df.index = df.index.tz_localize(None)
    df.index.name = "date"
    df.to_csv("d_spx.csv")
    print(f"  OK d_spx.csv ({len(df)} rows)")


def fetch_gold():
    print("[4/6] Gold futures (yfinance GC=F)...")
    yf  = _yf()
    tk  = yf.Ticker("GC=F")
    df  = tk.history(start=START, end=END, auto_adjust=True)
    if df.empty:
        print("  GC=F no data - fallback to IAU")
        tk  = yf.Ticker("IAU")
        df  = tk.history(start=START, end=END, auto_adjust=True)
    df  = df[["Close"]].rename(columns={"Close": "gold"})
    df.index = df.index.tz_localize(None)
    df.index.name = "date"
    df.to_csv("d_gold.csv")
    print(f"  OK d_gold.csv ({len(df)} rows)")


def fetch_bond():
    print("[5/6] US 10yr Treasury (yfinance ^TNX)...")
    yf  = _yf()
    tk  = yf.Ticker("^TNX")
    df  = tk.history(start=START, end=END, auto_adjust=True)
    df  = df[["Close"]].rename(columns={"Close": "y10"})
    df.index = df.index.tz_localize(None)
    df.index.name = "date"
    df.to_csv("d_bond.csv")
    print(f"  OK d_bond.csv ({len(df)} rows)")


def fetch_us_stocks():
    print(f"[6/6] US large-cap stocks x{len(US_UNIVERSE)} (yfinance, 5yr)...")
    yf       = _yf()
    all_data = []
    for ticker in US_UNIVERSE:
        try:
            tk  = yf.Ticker(ticker)
            df  = tk.history(start=STOCK_START, end=END, auto_adjust=True)
            df  = df[["Close"]].rename(columns={"Close": "close"})
            df.index = df.index.tz_localize(None)
            df["Name"] = ticker
            df.index.name = "date"
            df = df.reset_index()[["date", "Name", "close"]]
            all_data.append(df)
            print(f"  {ticker}: {len(df)} rows")
        except Exception as e:
            print(f"  {ticker}: FAILED - {e}")

    if all_data:
        combined = pd.concat(all_data, ignore_index=True)
        combined.to_csv("all_stocks_5yr.csv", index=False)
        print(f"  OK all_stocks_5yr.csv ({len(combined)} rows)")
    else:
        print("  FAIL: no stock data downloaded")


if __name__ == "__main__":
    print(f"=== Downloading SAMPLE data ({START} ~ {END}) ===\n")
    fetch_kospi()
    fetch_usdkrw()
    fetch_spx()
    fetch_gold()
    fetch_bond()
    fetch_us_stocks()
    print("\n=== Done! Run: python quantletter_pipeline.py ===")
