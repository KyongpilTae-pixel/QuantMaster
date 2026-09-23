"""US Event Study v2 — batch yfinance download (thread-safe)."""
import sys, io, json, warnings
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import yfinance as yf

UNIVERSE = [
    "AAPL","MSFT","GOOGL","META","NVDA","AMZN","INTC","CSCO","ORCL","IBM",
    "QCOM","TXN","AVGO","MU","ADI","AMAT","LRCX","KLAC","MCHP","SWKS",
    "JPM","BAC","WFC","GS","MS","C","BRK-B","AXP","USB","PNC",
    "TFC","COF","MET","PRU","AFL","ALL","CB","HIG","MMC","AON",
    "JNJ","PFE","UNH","ABBV","MRK","ABT","TMO","DHR","BMY","AMGN",
    "GILD","CVS","LLY","MDT","ISRG","SYK","BDX","BSX","ZBH","EW",
    "WMT","HD","PG","KO","PEP","MCD","SBUX","NKE","TGT","COST",
    "DIS","VZ","T","CMCSA","NFLX","LOW","TJX","EBAY","DLTR","DG",
    "XOM","CVX","COP","SLB","HAL","CAT","BA","GE","HON","MMM",
    "DE","EMR","LMT","RTX","NOC","UPS","FDX","CSX","NSC","UNP",
]

import random
random.seed(42)
SAMPLE = random.sample(UNIVERSE, 80)

MA_WINDOW = 200
STOP = -0.10
COOLDOWN = 30
HOLD_12M = 252
START_DATE = "2019-01-01"
DOWNLOAD_START = "2016-01-01"

print(f"배치 다운로드: {len(SAMPLE)}종목 ...", flush=True)

# Single batch download — yfinance internally handles multi-ticker as one request
raw = yf.download(
    SAMPLE,
    start=DOWNLOAD_START,
    end="2026-01-01",
    auto_adjust=True,
    progress=True,
    group_by="ticker",
    threads=True,
)

print("다운로드 완료. 신호 탐지 시작 ...", flush=True)


def get_close(ticker: str) -> pd.Series | None:
    try:
        if len(SAMPLE) == 1:
            close = raw["Close"].dropna()
        else:
            close = raw[ticker]["Close"].dropna()
        if hasattr(close, 'columns'):
            close = close.iloc[:, 0]
        close.index = pd.to_datetime(close.index).tz_localize(None)
        if len(close) < 300:
            return None
        return close.sort_index()
    except Exception as e:
        return None


def find_signals(close: pd.Series):
    ma200 = close.rolling(MA_WINDOW, min_periods=MA_WINDOW).mean()
    ratio = close / ma200
    prev_ratio = ratio.shift(1)

    start = pd.Timestamp(START_DATE)
    touch_list, reclaim_list = [], []
    last_touch = -9999
    last_reclaim = -9999

    for i in range(len(close)):
        if close.index[i] < start:
            continue
        r = ratio.iloc[i]
        pr = prev_ratio.iloc[i]
        if pd.isna(r) or pd.isna(pr):
            continue

        if 1.00 <= r <= 1.05 and i - last_touch >= COOLDOWN:
            touch_list.append(i)
            last_touch = i

        if pr < 1.00 and r >= 1.00 and i - last_reclaim >= COOLDOWN:
            reclaim_list.append(i)
            last_reclaim = i

    return touch_list, reclaim_list


def calc_forward(close: pd.Series, idx: int, entry_price: float):
    n = len(close)
    stop_price = entry_price * (1 + STOP)
    stop_hit_day = None

    for k in range(1, HOLD_12M + 1):
        if idx + k >= n:
            break
        if close.iloc[idx + k] <= stop_price:
            stop_hit_day = k
            break

    exit_idx = idx + HOLD_12M
    if stop_hit_day is not None:
        ret12m = STOP
    elif exit_idx < n:
        ret12m = (close.iloc[exit_idx] / entry_price) - 1
    else:
        ret12m = None

    mdd = 0.0
    end_k = stop_hit_day if stop_hit_day else min(HOLD_12M, n - idx - 1)
    for k in range(1, end_k + 1):
        if idx + k >= n:
            break
        r = (close.iloc[idx + k] / entry_price) - 1
        if r < mdd:
            mdd = r

    return {"ret12m": ret12m, "stop_hit": stop_hit_day is not None, "mdd": mdd}


all_trades = []
failed = []

for tk in SAMPLE:
    close = get_close(tk)
    if close is None:
        failed.append(tk)
        print(f"  {tk}: 실패", flush=True)
        continue

    touch_idxs, reclaim_idxs = find_signals(close)
    rows = []
    for sig_type, idxs in [("touch", touch_idxs), ("reclaim", reclaim_idxs)]:
        for idx in idxs:
            ep = float(close.iloc[idx])
            fwd = calc_forward(close, idx, ep)
            rows.append({
                "ticker": tk,
                "date": close.index[idx].strftime("%Y-%m-%d"),
                "type": sig_type,
                "entry_price": round(ep, 2),
                "ret12m": round(fwd["ret12m"] * 100, 2) if fwd["ret12m"] is not None else None,
                "stop_hit": fwd["stop_hit"],
                "mdd": round(fwd["mdd"] * 100, 2),
            })

    all_trades.extend(rows)
    tt = sum(1 for r in rows if r["type"] == "touch")
    rr = sum(1 for r in rows if r["type"] == "reclaim")
    print(f"  {tk}: touch={tt} reclaim={rr}", flush=True)


def aggregate(trades, sig_type):
    t = [x for x in trades if x["type"] == sig_type]
    ret12 = [x["ret12m"] for x in t if x["ret12m"] is not None]
    mdds = [x["mdd"] for x in t]
    n = len(t)
    if n == 0:
        return {"count": 0}
    years = (pd.Timestamp("2025-12-31") - pd.Timestamp(START_DATE)).days / 365.25
    return {
        "count": n,
        "annual_freq": round(n / years, 1),
        "win_rate_12m": round(sum(1 for r in ret12 if r > 0) / len(ret12) * 100, 1) if ret12 else None,
        "avg_ret_12m": round(np.mean(ret12), 2) if ret12 else None,
        "median_ret_12m": round(np.median(ret12), 2) if ret12 else None,
        "avg_mdd": round(np.mean(mdds), 2) if mdds else None,
        "stop_rate": round(sum(1 for x in t if x["stop_hit"]) / n * 100, 1),
    }


touch_agg = aggregate(all_trades, "touch")
reclaim_agg = aggregate(all_trades, "reclaim")

print(f"\n실패: {failed}", flush=True)
print(f"\n[요약]")
for label, agg in [("TOUCH", touch_agg), ("RECLAIM", reclaim_agg)]:
    print(f"{label}: 신호수={agg.get('count')} 연간빈도={agg.get('annual_freq')} "
          f"12M승률={agg.get('win_rate_12m')}% 평균={agg.get('avg_ret_12m')}% "
          f"중앙값={agg.get('median_ret_12m')}% 평균MDD={agg.get('avg_mdd')}% "
          f"손절율={agg.get('stop_rate')}%", flush=True)

print("\n[연도별]")
for yr in range(2019, 2026):
    tc = [x for x in all_trades if x["date"].startswith(str(yr)) and x["type"]=="touch"]
    rc = [x for x in all_trades if x["date"].startswith(str(yr)) and x["type"]=="reclaim"]
    t_ret = [x["ret12m"] for x in tc if x["ret12m"] is not None]
    r_ret = [x["ret12m"] for x in rc if x["ret12m"] is not None]
    t_wr = f"{round(sum(1 for r in t_ret if r>0)/len(t_ret)*100,1)}%" if t_ret else "–"
    r_wr = f"{round(sum(1 for r in r_ret if r>0)/len(r_ret)*100,1)}%" if r_ret else "–"
    t_avg = f"{np.mean(t_ret):+.1f}%" if t_ret else "–"
    r_avg = f"{np.mean(r_ret):+.1f}%" if r_ret else "–"
    print(f"  {yr}: touch={len(tc)} wr={t_wr} avg={t_avg} | reclaim={len(rc)} wr={r_wr} avg={r_avg}", flush=True)

out_json = r"C:\project\quant\us_eventstudy_results_v2.json"
output = {
    "universe_size": len(SAMPLE),
    "failed_tickers": failed,
    "successful_tickers": len(SAMPLE) - len(failed),
    "period": f"{START_DATE} to 2025-12-31",
    "methodology": {
        "ma_window": MA_WINDOW,
        "stop": STOP,
        "cooldown_days": COOLDOWN,
        "hold_12m_days": HOLD_12M,
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
print(f"\n저장: {out_json}")
print("완료")
