"""GP strategy trade log analysis for 3 KR stocks."""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import pandas as pd
import numpy as np

STOCKS = [
    ("000810", "삼성화재", "data_000810_samsungfire.csv"),
    ("032830", "삼성생명", "data_032830_samsunglife.csv"),
    ("010130", "고려아연", "data_010130_koreazinc.csv"),
]

STOP = -0.10
LOOKBACK = 750  # MA200 확인 기간 (trading days)
MA_WINDOW = 200
HOLD_DAYS_3M = 63
HOLD_DAYS_6M = 126
HOLD_DAYS_12M = 252

def compute_ma200_ratio(close, window=200):
    """close / MA200 ratio"""
    ma = close.rolling(window, min_periods=window).mean()
    return close / ma

def find_touch_signals(close, ma200_ratio, min_ratio=0.95, max_ratio=1.05):
    """MA200 touch: price is within 0~5% above MA200"""
    prev = close.shift(1)
    prev_ratio = ma200_ratio.shift(1)
    # Touch: ratio between 1.0 and 1.05 (0~5% above MA200)
    touch = (ma200_ratio >= 1.0) & (ma200_ratio <= max_ratio)
    # Also from above: was further above, now touching
    return touch

def find_reclaim_signals(close, ma200_ratio):
    """MA200 reclaim: previous close was below MA200, current close is above"""
    prev_ratio = ma200_ratio.shift(1)
    reclaim = (prev_ratio < 1.0) & (ma200_ratio >= 1.0)
    return reclaim

def calc_returns_and_stop(close, entry_idx, entry_price):
    """Calculate forward returns and stop hit info."""
    n = len(close)
    results = {}
    # Check stop first
    stop_hit_day = None
    stop_price = entry_price * (1 + STOP)
    for k in range(1, HOLD_DAYS_12M + 1):
        if entry_idx + k >= n:
            break
        if close.iloc[entry_idx + k] <= stop_price:
            stop_hit_day = k
            break
    results["stop_hit"] = stop_hit_day is not None
    results["stop_hit_day"] = stop_hit_day

    for label, days in [("ret_3m", HOLD_DAYS_3M), ("ret_6m", HOLD_DAYS_6M), ("ret_12m", HOLD_DAYS_12M)]:
        exit_idx = entry_idx + days
        if stop_hit_day and stop_hit_day <= days:
            # Stop hit before this horizon
            results[label] = STOP
        elif exit_idx < n:
            results[label] = (close.iloc[exit_idx] / entry_price) - 1
        else:
            results[label] = None
    return results

def bnh_stats(close, start_date="2019-01-01"):
    """Buy and hold from start_date."""
    s = close[close.index >= start_date]
    if len(s) < 2:
        return {}
    rets = s.pct_change().dropna()
    total = (s.iloc[-1] / s.iloc[0]) - 1
    n_years = (s.index[-1] - s.index[0]).days / 365.25
    cagr = (1 + total) ** (1 / n_years) - 1 if n_years > 0 else 0
    cum = (1 + rets).cumprod()
    roll_max = cum.cummax()
    dd = (cum - roll_max) / roll_max
    mdd = dd.min()
    sharpe = (rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0
    return {"cagr": round(cagr * 100, 2), "mdd": round(mdd * 100, 2), "sharpe": round(sharpe, 3), "total_ret": round(total * 100, 2)}

results_all = {}

for code, name, fname in STOCKS:
    path = rf"C:\project\quant\{fname}"
    df = pd.read_csv(path, encoding="utf-8-sig", index_col="date", parse_dates=True)
    df.columns = [c.lower() for c in df.columns]
    close = df["close"].dropna()
    close = close.sort_index()

    ma_ratio = compute_ma200_ratio(close)
    touch_sig = find_touch_signals(close, ma_ratio)
    reclaim_sig = find_reclaim_signals(close, ma_ratio)

    # Filter from 2019-01-01 (need 750 days prior for LOOKBACK context, MA200 needs 200 days)
    start_date = pd.Timestamp("2019-01-01")

    trades = []
    used_indices = set()  # avoid double-entry within 30 days

    for entry_type, signals in [("touch", touch_sig), ("reclaim", reclaim_sig)]:
        sig_dates = signals[signals & (signals.index >= start_date)].index
        last_entry_idx = -999
        for sig_date in sig_dates:
            idx = close.index.get_loc(sig_date)
            if idx - last_entry_idx < 30:  # cooldown 30 days
                continue
            if not (0 <= idx < len(close)):
                continue
            ma_r = ma_ratio.iloc[idx]
            if pd.isna(ma_r):
                continue
            entry_price = close.iloc[idx]
            ma200_gap_pct = round((ma_r - 1) * 100, 2)
            fwd = calc_returns_and_stop(close, idx, entry_price)
            trades.append({
                "code": code,
                "name": name,
                "entry_date": sig_date.strftime("%Y-%m-%d"),
                "entry_price": entry_price,
                "entry_type": entry_type,
                "ma200_gap_pct": ma200_gap_pct,
                "ret_3m": round(fwd["ret_3m"] * 100, 2) if fwd["ret_3m"] is not None else None,
                "ret_6m": round(fwd["ret_6m"] * 100, 2) if fwd["ret_6m"] is not None else None,
                "ret_12m": round(fwd["ret_12m"] * 100, 2) if fwd["ret_12m"] is not None else None,
                "stop_hit": fwd["stop_hit"],
                "stop_hit_day": fwd["stop_hit_day"],
            })
            last_entry_idx = idx

    bnh = bnh_stats(close)
    touch_trades = [t for t in trades if t["entry_type"] == "touch"]
    reclaim_trades = [t for t in trades if t["entry_type"] == "reclaim"]

    def avg_ret(ts, key):
        vals = [t[key] for t in ts if t[key] is not None]
        return round(np.mean(vals), 2) if vals else None

    def win_rate(ts, key):
        vals = [t[key] for t in ts if t[key] is not None]
        return round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1) if vals else None

    results_all[code] = {
        "name": name,
        "bnh": bnh,
        "trades": trades,
        "summary": {
            "touch": {
                "count": len(touch_trades),
                "stop_hit_rate": round(sum(t["stop_hit"] for t in touch_trades) / len(touch_trades) * 100, 1) if touch_trades else 0,
                "avg_ret_3m": avg_ret(touch_trades, "ret_3m"),
                "avg_ret_6m": avg_ret(touch_trades, "ret_6m"),
                "avg_ret_12m": avg_ret(touch_trades, "ret_12m"),
                "win_rate_12m": win_rate(touch_trades, "ret_12m"),
            },
            "reclaim": {
                "count": len(reclaim_trades),
                "stop_hit_rate": round(sum(t["stop_hit"] for t in reclaim_trades) / len(reclaim_trades) * 100, 1) if reclaim_trades else 0,
                "avg_ret_3m": avg_ret(reclaim_trades, "ret_3m"),
                "avg_ret_6m": avg_ret(reclaim_trades, "ret_6m"),
                "avg_ret_12m": avg_ret(reclaim_trades, "ret_12m"),
                "win_rate_12m": win_rate(reclaim_trades, "ret_12m"),
            },
        }
    }
    print(f"[{code} {name}] touch={len(touch_trades)}건 reclaim={len(reclaim_trades)}건 B&H CAGR={bnh.get('cagr')}%")

# Save JSON
out = r"C:\project\quant\gp_tradelog_3stocks.json"
with open(out, "w", encoding="utf-8") as f:
    json.dump(results_all, f, ensure_ascii=False, indent=2, default=str)
print(f"\n저장: {out}")

# Print trade logs
for code, name, _ in STOCKS:
    r = results_all[code]
    print(f"\n{'='*60}")
    print(f"{code} {r['name']} — 트레이드 로그")
    print(f"{'='*60}")
    print(f"{'날짜':<12} {'진입유형':<8} {'진입가':>8} {'MA200괴리%':>10} {'3M%':>7} {'6M%':>7} {'12M%':>7} {'손절'}")
    for t in r["trades"]:
        stop_str = f"D{t['stop_hit_day']}" if t["stop_hit"] else "-"
        r3 = f"{t['ret_3m']:+.1f}" if t["ret_3m"] is not None else "N/A"
        r6 = f"{t['ret_6m']:+.1f}" if t["ret_6m"] is not None else "N/A"
        r12 = f"{t['ret_12m']:+.1f}" if t["ret_12m"] is not None else "N/A"
        print(f"{t['entry_date']:<12} {t['entry_type']:<8} {t['entry_price']:>8,.0f} {t['ma200_gap_pct']:>10.1f} {r3:>7} {r6:>7} {r12:>7} {stop_str}")
    s = r["summary"]
    print(f"\nTouch: {s['touch']['count']}건 손절율={s['touch']['stop_hit_rate']}% 평균12M={s['touch']['avg_ret_12m']}% 승률={s['touch']['win_rate_12m']}%")
    print(f"Reclaim: {s['reclaim']['count']}건 손절율={s['reclaim']['stop_hit_rate']}% 평균12M={s['reclaim']['avg_ret_12m']}% 승률={s['reclaim']['win_rate_12m']}%")
    print(f"B&H: CAGR={r['bnh'].get('cagr')}% MDD={r['bnh'].get('mdd')}% Sharpe={r['bnh'].get('sharpe')}")
