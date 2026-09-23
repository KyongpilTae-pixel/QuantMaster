"""US Event Study v3 — growth gate + 12M-complete signals only.
cloud-002 spec: ratio250>=70% AND MA200 rising, exclude incomplete 12M.
"""
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
RATIO250_WINDOW = 250
MA_SLOPE_LAG = 20
MIN_RATIO250 = 0.70       # growth gate: 70%+ days above MA200
STOP = -0.10
COOLDOWN = 30
HOLD_12M = 252
START_DATE = "2019-01-01"
DOWNLOAD_START = "2015-01-01"   # need extra warmup for ratio250+MA200

print(f"배치 다운로드: {len(SAMPLE)}종목 ...", flush=True)
raw = yf.download(
    SAMPLE,
    start=DOWNLOAD_START,
    end="2026-01-01",
    auto_adjust=True,
    progress=True,
    group_by="ticker",
    threads=True,
)
print("다운로드 완료. 분석 시작 ...", flush=True)


def get_close(ticker):
    try:
        close = raw[ticker]["Close"].dropna()
        if hasattr(close, 'columns'):
            close = close.iloc[:, 0]
        close.index = pd.to_datetime(close.index).tz_localize(None)
        return close.sort_index() if len(close) >= 500 else None
    except:
        return None


def growth_gate(close, ma200, i):
    """True if ratio250 >= 70% AND MA200 is rising at index i."""
    start_i = max(0, i - RATIO250_WINDOW + 1)
    window = close.iloc[start_i:i + 1]
    ma_window = ma200.iloc[start_i:i + 1]
    valid = ma_window.dropna()
    if len(valid) < RATIO250_WINDOW * 0.8:
        return False
    ratio250 = (window > ma_window).sum() / len(window)
    if ratio250 < MIN_RATIO250:
        return False
    # MA200 rising: ma[t] > ma[t-20]
    if i < MA_SLOPE_LAG or pd.isna(ma200.iloc[i]) or pd.isna(ma200.iloc[i - MA_SLOPE_LAG]):
        return False
    return ma200.iloc[i] > ma200.iloc[i - MA_SLOPE_LAG]


def find_signals(close):
    ma200 = close.rolling(MA_WINDOW, min_periods=MA_WINDOW).mean()
    ratio = close / ma200
    prev_ratio = ratio.shift(1)

    start = pd.Timestamp(START_DATE)
    n = len(close)
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

        # 12M completeness check: must have 252 days forward
        if i + HOLD_12M >= n:
            continue  # cloud-002: "12M 미충족 신호 제외"

        # Touch: 0~+5% above MA200
        if 1.00 <= r <= 1.05 and i - last_touch >= COOLDOWN:
            if growth_gate(close, ma200, i):
                touch_list.append(i)
                last_touch = i

        # Reclaim: prev below, current above MA200
        if pr < 1.00 and r >= 1.00 and i - last_reclaim >= COOLDOWN:
            if growth_gate(close, ma200, i):
                reclaim_list.append(i)
                last_reclaim = i

    return touch_list, reclaim_list


def calc_forward(close, idx, entry_price):
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
        ret12m = None  # shouldn't happen due to pre-filter

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
gate_stats = {}   # how many signals survived growth gate

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
            if fwd["ret12m"] is None:
                continue
            rows.append({
                "ticker": tk,
                "date": close.index[idx].strftime("%Y-%m-%d"),
                "type": sig_type,
                "entry_price": round(ep, 2),
                "ret12m": round(fwd["ret12m"] * 100, 2),
                "stop_hit": fwd["stop_hit"],
                "mdd": round(fwd["mdd"] * 100, 2),
            })

    all_trades.extend(rows)
    tt = sum(1 for r in rows if r["type"] == "touch")
    rr = sum(1 for r in rows if r["type"] == "reclaim")
    gate_stats[tk] = {"touch": tt, "reclaim": rr}
    print(f"  {tk}: touch={tt} reclaim={rr}", flush=True)


def aggregate(trades, sig_type):
    t = [x for x in trades if x["type"] == sig_type]
    ret12 = [x["ret12m"] for x in t]
    mdds = [x["mdd"] for x in t]
    n = len(t)
    if n == 0:
        return {"count": 0}
    # effective years: 2019-01-01 to ~2024-12-31 (last year excluded)
    years = (pd.Timestamp("2024-12-31") - pd.Timestamp(START_DATE)).days / 365.25
    tickers = len(set(x["ticker"] for x in t))
    return {
        "count": n,
        "annual_freq_total": round(n / years, 1),
        "annual_freq_per_ticker": round(n / years / tickers, 2),
        "annual_freq_top10": round(n / years / tickers * 10, 1),
        "win_rate_12m": round(sum(1 for r in ret12 if r > 0) / len(ret12) * 100, 1),
        "avg_ret_12m": round(float(np.mean(ret12)), 2),
        "median_ret_12m": round(float(np.median(ret12)), 2),
        "avg_mdd": round(float(np.mean(mdds)), 2),
        "stop_rate": round(sum(1 for x in t if x["stop_hit"]) / n * 100, 1),
    }


touch_agg = aggregate(all_trades, "touch")
reclaim_agg = aggregate(all_trades, "reclaim")

print(f"\n실패: {failed}")
print(f"\n[요약 — 성장 게이트(ratio250≥70%+MA200상승) + 12M완성 신호만]")
for label, agg in [("TOUCH", touch_agg), ("RECLAIM", reclaim_agg)]:
    print(f"{label}: 신호수={agg.get('count')} 연간빈도(전체)={agg.get('annual_freq_total')} "
          f"종목당={agg.get('annual_freq_per_ticker')} top10바스켓={agg.get('annual_freq_top10')} "
          f"12M승률={agg.get('win_rate_12m')}% 평균={agg.get('avg_ret_12m')}% "
          f"중앙값={agg.get('median_ret_12m')}% 평균MDD={agg.get('avg_mdd')}% "
          f"손절율={agg.get('stop_rate')}%")

print("\n[연도별]")
for yr in range(2019, 2025):
    tc = [x for x in all_trades if x["date"].startswith(str(yr)) and x["type"] == "touch"]
    rc = [x for x in all_trades if x["date"].startswith(str(yr)) and x["type"] == "reclaim"]
    t_ret = [x["ret12m"] for x in tc]
    r_ret = [x["ret12m"] for x in rc]
    t_wr = f"{round(sum(1 for r in t_ret if r>0)/len(t_ret)*100,1)}%" if t_ret else "–"
    r_wr = f"{round(sum(1 for r in r_ret if r>0)/len(r_ret)*100,1)}%" if r_ret else "–"
    t_avg = f"{np.mean(t_ret):+.1f}%" if t_ret else "–"
    r_avg = f"{np.mean(r_ret):+.1f}%" if r_ret else "–"
    print(f"  {yr}: touch={len(tc)} wr={t_wr} avg={t_avg} | reclaim={len(rc)} wr={r_wr} avg={r_avg}")

out_json = r"C:\project\quant\us_eventstudy_results_v3.json"
output = {
    "version": "v3",
    "universe_size": len(SAMPLE),
    "failed_tickers": failed,
    "successful_tickers": len(SAMPLE) - len(failed),
    "period": f"{START_DATE} to 2024-12-31 (12M-complete only)",
    "methodology": {
        "ma_window": MA_WINDOW,
        "growth_gate_ratio250": f">= {MIN_RATIO250}",
        "growth_gate_ma_slope": f"ma[t] > ma[t-{MA_SLOPE_LAG}]",
        "stop": STOP,
        "cooldown_days": COOLDOWN,
        "hold_12m_days": HOLD_12M,
        "touch_range": "0% to +5% above MA200",
        "reclaim": "prev close below MA200, current close above",
        "incomplete_12m": "excluded",
    },
    "summary": {"touch": touch_agg, "reclaim": reclaim_agg},
    "trades": all_trades,
}
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\n저장: {out_json}")
print("완료")
