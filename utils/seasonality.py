"""
계절성 분석 (Seasonality Analysis)
진입 신호별 월별 EV — 어떤 달에 진입했을 때 성과가 좋은가?
"""

import numpy as np
import pandas as pd
from utils.trend_scanner import _ema, _HALFLIFE_YEARS

_MIN_MONTH_SAMPLES = 3

_MONTH_KR = [
    "", "1월", "2월", "3월", "4월", "5월", "6월",
    "7월", "8월", "9월", "10월", "11월", "12월",
]


def _empty(m: int) -> dict:
    return {
        "month_num":      m,
        "month_kr":       _MONTH_KR[m],
        "ev":             None,
        "ev_str":         "-",
        "win_rate":       0.0,
        "win_rate_str":   "-",
        "avg_profit":     0.0,
        "avg_profit_str": "-",
        "avg_loss":       0.0,
        "avg_loss_str":   "-",
        "pl_ratio":       None,
        "pl_ratio_str":   "-",
        "sample_n":       0,
        "sample_n_str":   "0",
        "has_data":       False,
        "ev_high":        False,
        "ev_positive":    False,
        "win_rate_high":  False,
    }


def _row(m: int, win_rate_pct: float, ev, avg_profit, avg_loss, pl_ratio, sample_n: int) -> dict:
    return {
        "month_num":      m,
        "month_kr":       _MONTH_KR[m],
        "ev":             round(ev, 3) if ev is not None else None,
        "ev_str":         f"{ev:.3f}" if ev is not None else "-",
        "win_rate":       win_rate_pct,
        "win_rate_str":   f"{win_rate_pct:.1f}%" if win_rate_pct else "-",
        "avg_profit":     avg_profit or 0.0,
        "avg_profit_str": f"+{avg_profit:.1f}%" if avg_profit else "-",
        "avg_loss":       avg_loss or 0.0,
        "avg_loss_str":   f"-{avg_loss:.1f}%" if avg_loss else "-",
        "pl_ratio":       round(pl_ratio, 2) if pl_ratio is not None else None,
        "pl_ratio_str":   f"{pl_ratio:.2f}" if pl_ratio is not None else "-",
        "sample_n":       sample_n,
        "sample_n_str":   str(sample_n),
        "has_data":       ev is not None or sample_n >= _MIN_MONTH_SAMPLES,
        "ev_high":        (ev or 0) >= 1.0,
        "ev_positive":    (ev or 0) > 0,
        "win_rate_high":  win_rate_pct >= 60.0,
    }


def calc_monthly_seasonality(
    df: pd.DataFrame,
    entry_type: str,
    ma_period: int,
    hold_days: int = 20,
    halflife_years: float = _HALFLIFE_YEARS,
) -> list:
    """진입 신호별 12개월 계절성 EV — hold_days 일 보유 기준"""
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    n     = len(close)

    empty_all = [_empty(m) for m in range(1, 13)]

    if n < hold_days + 20:
        return empty_all

    lam = np.log(2) / (halflife_years * 252)

    if entry_type == "pullback":
        ma     = _ema(close, ma_period)
        gap    = (close - ma) / ma * 100
        signal = ((gap >= -2.0) & (gap <= 3.0)).values
    elif entry_type == "breakout_n":
        prev_high = high.shift(1).rolling(ma_period).max()
        signal    = (close > prev_high).values
    elif entry_type == "box_breakout":
        box_high  = high.shift(1).rolling(61).max()
        box_low   = low.shift(1).rolling(61).min()
        box_range = (box_high - box_low) / box_low * 100
        bp        = (close - box_high) / box_high * 100
        signal    = (
            (box_range <= 20) & (close > box_high) & (bp > 0) & (bp < 5.0)
        ).values
    else:
        return empty_all

    valid_idx = np.where(signal[: n - hold_days])[0]
    if len(valid_idx) == 0:
        return empty_all

    close_arr    = close.values
    entry_prices = close_arr[valid_idx]
    exit_prices  = close_arr[valid_idx + hold_days]
    returns      = (exit_prices - entry_prices) / entry_prices * 100
    days_ago     = (n - 1) - valid_idx
    weights      = np.exp(-lam * days_ago)
    months       = np.array([df.index[i].month for i in valid_idx])

    results = []
    for m in range(1, 13):
        mask = months == m
        if mask.sum() < _MIN_MONTH_SAMPLES:
            results.append(_empty(m))
            continue

        w       = weights[mask]
        r       = returns[mask]
        wins    = r > 0
        total_w = w.sum()

        if total_w == 0:
            results.append(_empty(m))
            continue

        win_rate = float(w[wins].sum() / total_w)

        if wins.sum() == 0 or (~wins).sum() == 0:
            results.append(_row(m, win_rate * 100, None, None, None, None, int(mask.sum())))
            continue

        avg_profit = float((r[wins]  * w[wins]).sum()  / w[wins].sum())
        avg_loss   = float(abs((r[~wins] * w[~wins]).sum() / w[~wins].sum()))
        pl_ratio   = avg_profit / avg_loss if avg_loss > 0 else None
        ev         = float(win_rate * pl_ratio - (1 - win_rate)) if pl_ratio else None

        results.append(_row(m, win_rate * 100, ev, avg_profit, avg_loss, pl_ratio, int(mask.sum())))

    return results
