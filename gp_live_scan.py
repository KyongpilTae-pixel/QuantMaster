import warnings; warnings.filterwarnings("ignore")
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

END   = datetime.today().strftime("%Y-%m-%d")
START = (datetime.today() - timedelta(days=365*4)).strftime("%Y-%m-%d")

KOSPI_TOP = [
    "005930","000660","207940","005380","051910","035420","006400","028260",
    "000270","105560","035720","055550","012330","066570","017670","032830",
    "003550","086790","009150","010130","011200","018260","302440","034020",
    "011170","033780","096770","003490","010950","030200","047050","051600",
    "034730","000810","005490","003670","090430","018880","009830","010140",
]

SP500_TOP = [
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","JPM","LLY",
    "V","UNH","XOM","MA","JNJ","PG","COST","HD","ABBV","MRK",
    "ORCL","CVX","CRM","BAC","KO","NFLX","AMD","PEP","WMT","TMO",
    "ACN","MCD","CSCO","ABT","GE","MS","NOW","ADBE","DHR","ISRG",
]

LOOKBACK = 750
TOP_N    = 10

def fetch(ticker, is_kr):
    try:
        if is_kr:
            df = fdr.DataReader(ticker, START, END)
        else:
            import yfinance as yf
            df = yf.download(ticker, start=START, end=END, progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
        if df is None or len(df) < 250:
            return ticker, None
        col_map = {str(c).lower(): c for c in df.columns}
        if "close" not in col_map:
            return ticker, None
        s = df[col_map["close"]]
        if isinstance(s, pd.DataFrame): s = s.iloc[:,0]
        s = s.squeeze()
        s.index = pd.to_datetime(s.index)
        if hasattr(s.index, "tz") and s.index.tz: s.index = s.index.tz_localize(None)
        return ticker, s.dropna()
    except:
        return ticker, None

def scan(tickers, is_kr, label):
    print(f"\n=== {label} GP 현재 신호 스캔 ===")
    prices = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for t, s in ex.map(lambda t: fetch(t, is_kr), tickers):
            if s is not None and len(s) >= 250:
                prices[t] = s

    results = []
    for t, s in prices.items():
        ma200 = s.rolling(200, min_periods=100).mean()
        last_price  = s.iloc[-1]
        last_ma200  = ma200.iloc[-1]
        if pd.isna(last_ma200) or last_ma200 <= 0:
            continue
        ratio = (last_price - last_ma200) / last_ma200
        # MA200 위 비율 (최근 LOOKBACK일)
        common = s[-LOOKBACK:].index.intersection(ma200[-LOOKBACK:].index)
        if len(common) < 200:
            continue
        above_ratio = (s.loc[common].values > ma200.loc[common].values).mean()
        if above_ratio < 0.70:
            continue
        # 12M 모멘텀
        date_12m = s.index[-1] - pd.DateOffset(months=12)
        past = s[s.index <= date_12m]
        if len(past) == 0:
            continue
        mom = last_price / past.iloc[-1] - 1
        results.append({
            "ticker": t,
            "price": round(last_price, 2),
            "ma200": round(last_ma200, 2),
            "ratio_pct": round(ratio * 100, 2),
            "above_ratio_pct": round(above_ratio * 100, 1),
            "mom_12m_pct": round(mom * 100, 1),
        })

    if not results:
        print("  성장주 판정(MA200 ratio>=70%) 종목 없음")
        return

    df = pd.DataFrame(results).sort_values("mom_12m_pct", ascending=False)
    top = df.head(TOP_N)

    # touch 조건: 0 <= ratio <= 5%
    touch = top[(top["ratio_pct"] >= 0) & (top["ratio_pct"] <= 5.0)]
    print(f"\n[성장주 판정 후보 Top{TOP_N}]")
    print(top[["ticker","price","ma200","ratio_pct","above_ratio_pct","mom_12m_pct"]].to_string(index=False))

    if len(touch) > 0:
        print(f"\n[GP Touch 신호 종목] (현재 MA200 0~5% 위)")
        print(touch[["ticker","price","ma200","ratio_pct","mom_12m_pct"]].to_string(index=False))
    else:
        print(f"\n[GP Touch 신호] 현재 없음 — 가장 가까운 종목:")
        closest = top.iloc[(top["ratio_pct"].apply(lambda x: abs(x) if x >= 0 else 999)).argsort()].head(3)
        print(closest[["ticker","price","ma200","ratio_pct","mom_12m_pct"]].to_string(index=False))

scan(KOSPI_TOP[:30], True,  "KR KOSPI")
scan(SP500_TOP[:40], False, "US S&P500")
