"""US Event Study: MA200 Touch/Reclaim Signals (2019-2025)
Methodology mirrors KR study: cloud-002 REQUEST specification.
"""
import sys, io, json, warnings
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

# 80 S&P500 stocks - large/mid cap, diverse sectors, all listed pre-2016
UNIVERSE = [
    # Technology
    "AAPL","MSFT","GOOGL","META","NVDA","AMZN","INTC","CSCO","ORCL","IBM",
    "QCOM","TXN","AVGO","MU","ADI","AMAT","LRCX","KLAC","MCHP","SWKS",
    # Financials
    "JPM","BAC","WFC","GS","MS","C","BRK-B","AXP","USB","PNC",
    "TFC","COF","MET","PRU","AFL","ALL","CB","HIG","MMC","AON",
    # Healthcare
    "JNJ","PFE","UNH","ABBV","MRK","ABT","TMO","DHR","BMY","AMGN",
    "GILD","CVS","LLY","MDT","ISRG","SYK","BDX","BSX","ZBH","EW",
    # Consumer / Retail
    "WMT","HD","PG","KO","PEP","MCD","SBUX","NKE","TGT","COST",
    "DIS","VZ","T","CMCSA","NFLX","LOW","TJX","EBAY","DLTR","DG",
    # Industrials / Energy / Materials
    "XOM","CVX","COP","SLB","HAL","CAT","BA","GE","HON","MMM",
    "DE","EMR","LMT","RTX","NOC","UPS","FDX","CSX","NSC","UNP",
]

assert len(UNIVERSE) == 100
# Sample 80 for requested count
import random
random.seed(42)
SAMPLE = random.sample(UNIVERSE, 80)

MA_WINDOW = 200
STOP = -0.10
COOLDOWN = 30
HOLD_12M = 252
START_DATE = "2019-01-01"
DOWNLOAD_START = "2016-01-01"  # need 200+ days warmup before 2019


def download_ohlcv(ticker: str) -> pd.Series | None:
    try:
        df = yf.download(ticker, start=DOWNLOAD_START, end="2026-01-01",
                         auto_adjust=True, progress=False)
        if df is None or len(df) < 300:
            return None
        close = df["Close"].dropna()
        if hasattr(close.columns, '__iter__'):
            close = close.iloc[:, 0]
        close.index = pd.to_datetime(close.index).tz_localize(None)
        return close
    except Exception as e:
        print(f"  [WARN] {ticker}: {e}", flush=True)
        return None


def find_signals(close: pd.Series):
    ma200 = close.rolling(MA_WINDOW, min_periods=MA_WINDOW).mean()
    ratio = close / ma200

    start = pd.Timestamp(START_DATE)
    touch_list, reclaim_list = [], []

    prev_ratio = ratio.shift(1)

    last_entry = {"touch": -9999, "reclaim": -9999}

    for i in range(len(close)):
        dt = close.index[i]
        if dt < start:
            continue
        r = ratio.iloc[i]
        pr = prev_ratio.iloc[i]
        if pd.isna(r) or pd.isna(pr):
            continue

        # Touch: 0~+5% above MA200 (ratio 1.00~1.05)
        if 1.00 <= r <= 1.05:
            if i - last_entry["touch"] >= COOLDOWN:
                touch_list.append(i)
                last_entry["touch"] = i

        # Reclaim: prev below MA200, current above
        if pr < 1.00 and r >= 1.00:
            if i - last_entry["reclaim"] >= COOLDOWN:
                reclaim_list.append(i)
                last_entry["reclaim"] = i

    return touch_list, reclaim_list


def calc_forward(close: pd.Series, idx: int, entry_price: float):
    n = len(close)
    stop_price = entry_price * (1 + STOP)
    stop_hit_day = None

    # Check stop
    for k in range(1, HOLD_12M + 1):
        if idx + k >= n:
            break
        if close.iloc[idx + k] <= stop_price:
            stop_hit_day = k
            break

    # 12M return
    exit_idx = idx + HOLD_12M
    if stop_hit_day is not None:
        ret12m = STOP
    elif exit_idx < n:
        ret12m = (close.iloc[exit_idx] / entry_price) - 1
    else:
        ret12m = None

    # MDD over holding period
    mdd = 0.0
    for k in range(1, min(HOLD_12M, n - idx)):
        r = (close.iloc[idx + k] / entry_price) - 1
        if r < mdd:
            mdd = r
        if stop_hit_day and k >= stop_hit_day:
            break

    return {"ret12m": ret12m, "stop_hit": stop_hit_day is not None, "mdd": mdd}


def analyze_stock(ticker: str):
    close = download_ohlcv(ticker)
    if close is None:
        return None

    touch_idxs, reclaim_idxs = find_signals(close)

    rows = []
    for sig_type, idxs in [("touch", touch_idxs), ("reclaim", reclaim_idxs)]:
        for idx in idxs:
            ep = close.iloc[idx]
            fwd = calc_forward(close, idx, ep)
            rows.append({
                "ticker": ticker,
                "date": close.index[idx].strftime("%Y-%m-%d"),
                "type": sig_type,
                "entry_price": round(float(ep), 2),
                "ret12m": round(fwd["ret12m"] * 100, 2) if fwd["ret12m"] is not None else None,
                "stop_hit": fwd["stop_hit"],
                "mdd": round(fwd["mdd"] * 100, 2),
            })
    return rows


def aggregate(trades, sig_type):
    t = [x for x in trades if x["type"] == sig_type]
    ret12 = [x["ret12m"] for x in t if x["ret12m"] is not None]
    mdds = [x["mdd"] for x in t]
    n = len(t)
    if n == 0:
        return {"count": 0}
    years = (pd.Timestamp("2025-12-31") - pd.Timestamp("2019-01-01")).days / 365.25
    return {
        "count": n,
        "annual_freq": round(n / years, 1),
        "win_rate_12m": round(sum(1 for r in ret12 if r > 0) / len(ret12) * 100, 1) if ret12 else None,
        "avg_ret_12m": round(np.mean(ret12), 2) if ret12 else None,
        "median_ret_12m": round(np.median(ret12), 2) if ret12 else None,
        "avg_mdd": round(np.mean(mdds), 2) if mdds else None,
        "stop_rate": round(sum(1 for x in t if x["stop_hit"]) / n * 100, 1),
    }


print(f"US Event Study — {len(SAMPLE)}종목 다운로드 시작", flush=True)
all_trades = []
failed = []

with ThreadPoolExecutor(max_workers=8) as pool:
    futures = {pool.submit(analyze_stock, tk): tk for tk in SAMPLE}
    done = 0
    for fut in as_completed(futures):
        tk = futures[fut]
        done += 1
        result = fut.result()
        if result is None:
            failed.append(tk)
            print(f"  [{done:02d}/{len(SAMPLE)}] {tk}: 실패", flush=True)
        else:
            all_trades.extend(result)
            tt = sum(1 for r in result if r["type"]=="touch")
            rr = sum(1 for r in result if r["type"]=="reclaim")
            print(f"  [{done:02d}/{len(SAMPLE)}] {tk}: touch={tt} reclaim={rr}", flush=True)

print(f"\n수집 완료: {len(SAMPLE)-len(failed)}종목 성공, {len(failed)}종목 실패", flush=True)
if failed:
    print(f"  실패: {failed}", flush=True)

# Aggregate results
touch_agg = aggregate(all_trades, "touch")
reclaim_agg = aggregate(all_trades, "reclaim")

# Year breakdown
print("\n[연도별 신호 분포]", flush=True)
for yr in range(2019, 2026):
    t_yr = sum(1 for x in all_trades if x["date"].startswith(str(yr)) and x["type"]=="touch")
    r_yr = sum(1 for x in all_trades if x["date"].startswith(str(yr)) and x["type"]=="reclaim")
    print(f"  {yr}: touch={t_yr} reclaim={r_yr}", flush=True)

print("\n[요약]")
for label, agg in [("TOUCH", touch_agg), ("RECLAIM", reclaim_agg)]:
    print(f"{label}: 신호수={agg.get('count')} 연간빈도={agg.get('annual_freq')} "
          f"12M승률={agg.get('win_rate_12m')}% 평균={agg.get('avg_ret_12m')}% "
          f"중앙값={agg.get('median_ret_12m')}% 평균MDD={agg.get('avg_mdd')}% "
          f"손절율={agg.get('stop_rate')}%", flush=True)

# Save JSON
out_json = r"C:\project\quant\us_eventstudy_results.json"
output = {
    "universe_size": len(SAMPLE),
    "failed_tickers": failed,
    "successful_tickers": len(SAMPLE) - len(failed),
    "period": "2019-01-01 to 2025-12-31",
    "methodology": {
        "ma_window": 200,
        "stop": -0.10,
        "cooldown_days": 30,
        "hold_12m_days": 252,
        "touch_range": "0% to +5% above MA200",
        "reclaim": "prev close below MA200, current close above",
    },
    "summary": {
        "touch": touch_agg,
        "reclaim": reclaim_agg,
    },
    "trades": all_trades,
}

with open(out_json, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2, default=str)
print(f"\n저장: {out_json}", flush=True)
print("완료", flush=True)
