"""글로벌 시장 모멘텀 전략 백테스트 — 4가지 전략 + 균등분산 비교 (월별 리밸런싱)."""

import math
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

_ASSETS = [
    {"key": "kr",   "code": "KS11"},
    {"key": "us",   "code": "SPY"},
    {"key": "cn",   "code": "SSEC"},
    {"key": "jp",   "code": "N225"},
    {"key": "bond", "code": "TLT"},
    {"key": "gold", "code": "GLD"},
]

_STRAT_NAMES = {
    "momentum": "단순모멘텀",
    "vaa":      "VAA",
    "ma200":    "MA200 필터",
    "invvol":   "역변동성",
    "equal":    "균등분산",
}


def _fetch_all_prices(years: int) -> dict[str, pd.Series]:
    end = datetime.today()
    start = end - timedelta(days=(years + 2) * 365)
    price_map: dict[str, pd.Series] = {}
    for asset in _ASSETS:
        try:
            df = fdr.DataReader(
                asset["code"],
                start.strftime("%Y-%m-%d"),
                end.strftime("%Y-%m-%d"),
            )
            if not df.empty and "Close" in df.columns:
                price_map[asset["key"]] = df["Close"].dropna()
        except Exception:
            pass
    return price_map


def _period_ret(prices: pd.Series, at_date: pd.Timestamp, days: int) -> float | None:
    sub = prices[prices.index <= at_date]
    if len(sub) < days + 1:
        return None
    return float(sub.iloc[-1] / sub.iloc[-(days + 1)] - 1) * 100


def _signal_momentum(prices: dict[str, pd.Series], at_date: pd.Timestamp) -> dict[str, float]:
    period_winners: dict[str, str] = {}
    for lbl, days in (("3m", 63), ("6m", 126), ("12m", 252)):
        best_key, best_ret = "cash", 0.0
        for key, p in prices.items():
            r = _period_ret(p, at_date, days)
            if r is not None and r > best_ret:
                best_ret, best_key = r, key
        period_winners[lbl] = best_key
    win_counts: dict[str, int] = {}
    for w in period_winners.values():
        win_counts[w] = win_counts.get(w, 0) + 1
    max_w = max(win_counts.values())
    cands = [k for k, v in win_counts.items() if v == max_w]
    winner = cands[0] if len(cands) == 1 else period_winners["12m"]
    return {} if winner == "cash" else {winner: 1.0}


def _signal_vaa(prices: dict[str, pd.Series], at_date: pd.Timestamp) -> dict[str, float]:
    scores: dict[str, float] = {}
    for key, p in prices.items():
        rets = {lbl: _period_ret(p, at_date, d) for lbl, d in (("1m", 21), ("3m", 63), ("6m", 126), ("12m", 252))}
        if all(v is not None for v in rets.values()):
            scores[key] = 12 * rets["1m"] + 4 * rets["3m"] + 2 * rets["6m"] + rets["12m"]  # type: ignore[operator]
    if not scores:
        return {}
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    return {} if scores[best] <= 0 else {best: 1.0}


def _signal_ma200(prices: dict[str, pd.Series], at_date: pd.Timestamp) -> dict[str, float]:
    eligible: dict[str, float] = {}
    for key, p in prices.items():
        sub = p[p.index <= at_date]
        if len(sub) >= 252 and float(sub.iloc[-1]) > float(sub.tail(200).mean()):
            r12 = _period_ret(p, at_date, 252)
            if r12 is not None:
                eligible[key] = r12
    if not eligible:
        return {}
    best = max(eligible, key=eligible.get)  # type: ignore[arg-type]
    return {best: 1.0}


def _signal_invvol(prices: dict[str, pd.Series], at_date: pd.Timestamp) -> dict[str, float]:
    vols: dict[str, float] = {}
    for key, p in prices.items():
        sub = p[p.index <= at_date]
        if len(sub) >= 61:
            v = float(sub.pct_change().dropna().tail(60).std() * math.sqrt(252) * 100)
            if v > 0:
                vols[key] = v
    if not vols:
        return {}
    total_inv = sum(1 / v for v in vols.values())
    return {k: (1 / v) / total_inv for k, v in vols.items()}


def _signal_equal(prices: dict[str, pd.Series], at_date: pd.Timestamp) -> dict[str, float]:
    available = [k for k, p in prices.items() if len(p[p.index <= at_date]) >= 2]
    if not available:
        return {}
    w = 1.0 / len(available)
    return {k: w for k in available}


def _apply_weights(
    weights: dict[str, float],
    prices: dict[str, pd.Series],
    from_dt: pd.Timestamp,
    to_dt: pd.Timestamp,
) -> float:
    if not weights:
        return 0.0
    total, wsum = 0.0, 0.0
    for key, w in weights.items():
        if key not in prices:
            continue
        p0 = prices[key][prices[key].index <= from_dt]
        p1 = prices[key][prices[key].index <= to_dt]
        if p0.empty or p1.empty:
            continue
        r = float(p1.iloc[-1]) / float(p0.iloc[-1]) - 1
        total += w * r
        wsum += w
    if wsum < 0.001:
        return 0.0
    return total / wsum * sum(weights.values())


def _calc_stats(rets: list[float], years_actual: float) -> dict:
    if not rets:
        return {"total_ret": "N/A", "cagr": "N/A", "mdd": "N/A", "sharpe": "N/A",
                "cagr_raw": -999.0, "is_best": False}
    cum, values = 1.0, []
    for r in rets:
        cum *= 1 + r
        values.append(cum)
    total_ret = values[-1] - 1
    cagr = (values[-1] ** (1 / years_actual) - 1) if years_actual > 0 else 0.0
    peak, mdd = 1.0, 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < mdd:
            mdd = dd
    arr = pd.Series(rets)
    sharpe = float(arr.mean() / arr.std() * math.sqrt(12)) if float(arr.std()) > 0 else 0.0
    return {
        "total_ret": f"{total_ret * 100:+.1f}%",
        "cagr": f"{cagr * 100:+.1f}%",
        "mdd": f"{mdd * 100:.1f}%",
        "sharpe": f"{sharpe:.2f}",
        "cagr_raw": round(cagr * 100, 2),
        "is_best": False,
    }


def run_backtest(years: int = 10) -> dict:
    """월별 리밸런싱 백테스트. 초기 자산 100 기준 포트폴리오 가치 추이 반환."""
    try:
        prices = _fetch_all_prices(years)
        if len(prices) < 2:
            return {"chart_data": [], "summary": [], "error": "데이터 부족"}

        end_dt = pd.Timestamp.today().normalize()
        start_dt = end_dt - pd.DateOffset(years=years)
        date_fmt = "%Y-%m"
        dates = pd.date_range(start=start_dt, end=end_dt, freq="ME")

        if len(dates) < 3:
            return {"chart_data": [], "summary": [], "error": "기간 부족"}

        signal_fns = {
            "momentum": _signal_momentum,
            "vaa":      _signal_vaa,
            "ma200":    _signal_ma200,
            "invvol":   _signal_invvol,
            "equal":    _signal_equal,
        }
        values = {k: 100.0 for k in signal_fns}
        monthly_rets: dict[str, list[float]] = {k: [] for k in signal_fns}
        chart_data: list[dict] = []

        for i in range(len(dates) - 1):
            sig_dt = dates[i]
            next_dt = dates[i + 1]
            row: dict = {"date": sig_dt.strftime(date_fmt)}
            for key, fn in signal_fns.items():
                w = fn(prices, sig_dt)
                r = _apply_weights(w, prices, sig_dt, next_dt)
                monthly_rets[key].append(r)
                values[key] *= 1 + r
                row[key] = round(values[key], 2)
            chart_data.append(row)

        years_actual = (dates[-1] - dates[0]).days / 365.25
        summary: list[dict] = []
        for key in signal_fns:
            stats = _calc_stats(monthly_rets[key], years_actual)
            stats["strategy"] = _STRAT_NAMES[key]
            stats["key"] = key
            summary.append(stats)

        best_cagr = max(s["cagr_raw"] for s in summary)
        for s in summary:
            s["is_best"] = s["cagr_raw"] == best_cagr

        return {"chart_data": chart_data, "summary": summary, "error": ""}

    except Exception as e:
        return {"chart_data": [], "summary": [], "error": str(e)}
