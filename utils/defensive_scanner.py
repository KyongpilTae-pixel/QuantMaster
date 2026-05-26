"""하락장 방어 종목 스캐너 — Beta, RS, Downside Capture 기반."""

import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

_INDEX_MAP = {"KOSPI": "KS11", "KOSDAQ": "KQ11"}
_INDEX_CACHE: dict = {}  # {(market, period_days, date_key): pd.Series}


def _get_market_returns(market: str, period_days: int) -> pd.Series:
    """시장 지수 일간 수익률 (당일 캐싱)."""
    today = datetime.today().strftime("%Y%m%d")
    key = (market, period_days, today)
    if key not in _INDEX_CACHE:
        index_code = _INDEX_MAP.get(market, "KS11")
        end = datetime.today()
        start = end - timedelta(days=period_days * 2)
        df = fdr.DataReader(
            index_code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        )
        _INDEX_CACHE[key] = df["Close"].pct_change().dropna().tail(period_days)
    return _INDEX_CACHE[key]


def _calc_one(args: tuple) -> dict | None:
    code, name, mktcap_eok, market, period_days = args
    try:
        market_ret = _get_market_returns(market, period_days)
        if market_ret.empty:
            return None

        end = datetime.today()
        start = end - timedelta(days=period_days * 2)
        df = fdr.DataReader(
            code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        )
        if df.empty or "Close" not in df.columns:
            return None

        stock_ret = df["Close"].pct_change().dropna().tail(period_days)
        close = float(df["Close"].iloc[-1])

        aligned = pd.concat(
            [market_ret.rename("market"), stock_ret.rename("stock")], axis=1
        ).dropna()

        if len(aligned) < max(period_days // 3, 10):
            return None

        m, s = aligned["market"], aligned["stock"]

        # Beta
        var_m = float(m.var())
        beta = round(float(m.cov(s)) / var_m, 2) if var_m > 1e-10 else None

        # RS (누적 수익률 비교)
        total_m = float((1 + m).prod() - 1)
        total_s = float((1 + s).prod() - 1)
        rs = round(total_s / abs(total_m), 2) if abs(total_m) > 0.001 else None

        # 시장 하락일 분석
        down_mask = m < 0
        down_days = aligned[down_mask]
        n_down = int(down_mask.sum())

        if n_down >= 5:
            avg_m_down = float(down_days["market"].mean())
            avg_s_down = float(down_days["stock"].mean())
            dc = (
                round(avg_s_down / abs(avg_m_down) * 100, 1)
                if abs(avg_m_down) > 1e-6
                else None
            )
            up_on_down = round(float((down_days["stock"] > 0).mean() * 100), 1)
        else:
            dc = None
            up_on_down = None

        if beta is None or rs is None:
            return None

        # 당일 / 5일 수익률
        today_chg = round(float(stock_ret.iloc[-1]) * 100, 2) if len(stock_ret) >= 1 else None
        five_day_chg = (
            round(float((1 + stock_ret.tail(5)).prod() - 1) * 100, 2)
            if len(stock_ret) >= 5
            else None
        )

        return {
            "code": code,
            "name": name,
            "close": close,
            "mktcap_eok": mktcap_eok,
            "beta": beta,
            "rs": rs,
            "downside_capture": dc,
            "up_on_down_pct": up_on_down,
            "n_down_days": n_down,
            "today_chg": today_chg,
            "five_day_chg": five_day_chg,
        }
    except Exception:
        return None


def scan_defensive_stocks(
    market: str = "KOSPI",
    period_days: int = 60,
    max_beta: float = 0.8,
    min_mktcap_eok: int = 10_000,  # 기본 1조 = 10,000억
    top_n: int = 30,
) -> list[dict]:
    """하락장 방어 종목 스캔.

    Args:
        min_mktcap_eok: 최소 시가총액 (억원 단위). 기본 10,000억 = 1조원.
    Returns:
        list of dicts with rank/code/name/close/beta/rs/dc/up_on_down + bool flags
    """
    listing = fdr.StockListing(market)
    if listing.empty:
        return []

    # 컬럼 정규화
    cols_lower = {c.lower(): c for c in listing.columns}
    code_col = cols_lower.get("code") or cols_lower.get("symbol", listing.columns[0])
    name_col = cols_lower.get("name", listing.columns[1])
    cap_col = cols_lower.get("marcap") or cols_lower.get("marketcap")

    # 시가총액 필터 (Marcap은 원 단위)
    if cap_col and min_mktcap_eok > 0:
        listing = listing[
            listing[cap_col].fillna(0) >= min_mktcap_eok * 1e8
        ]
    if listing.empty:
        return []

    codes = listing[code_col].tolist()
    names = dict(zip(listing[code_col], listing[name_col]))
    caps = {}
    if cap_col:
        for _, row in listing.iterrows():
            caps[row[code_col]] = round(float(row[cap_col]) / 1e8, 0)

    # 지수 수익률 미리 캐싱
    _get_market_returns(market, period_days)

    args_list = [
        (c, names.get(c, c), caps.get(c, 0.0), market, period_days)
        for c in codes
    ]

    with ThreadPoolExecutor(max_workers=15) as ex:
        raw = list(ex.map(_calc_one, args_list))

    # 필터: beta < max_beta, rs > 0
    results = [
        r for r in raw
        if r is not None and r["beta"] < max_beta and r["rs"] > 0
    ]

    # 정렬: RS 높을수록 + Beta 낮을수록 + 하락포착률 낮을수록
    def _score(x):
        dc = x["downside_capture"] if x["downside_capture"] is not None else 100.0
        return (x["rs"], -x["beta"], -dc)

    results.sort(key=_score, reverse=True)
    top = results[:top_n]

    for i, r in enumerate(top):
        r["rank"] = i + 1
        cap = r["mktcap_eok"]
        r["mktcap_str"] = f"{cap/10000:.1f}조" if cap >= 10000 else f"{cap:,.0f}억"
        r["close_str"] = f"{r['close']:,.0f}"
        r["beta_str"] = f"{r['beta']:.2f}"
        r["rs_str"] = f"{r['rs']:.2f}"
        r["dc_str"] = (
            f"{r['downside_capture']:.1f}%" if r["downside_capture"] is not None else "-"
        )
        r["up_str"] = (
            f"{r['up_on_down_pct']:.1f}%" if r["up_on_down_pct"] is not None else "-"
        )
        # 당일/5일 표시 문자열 + bool 플래그
        t = r["today_chg"]
        f5 = r["five_day_chg"]
        r["today_chg_str"] = f"{t:+.2f}%" if t is not None else "-"
        r["five_day_chg_str"] = f"{f5:+.2f}%" if f5 is not None else "-"
        r["today_chg_positive"] = t is not None and t > 0
        r["five_day_chg_positive"] = f5 is not None and f5 > 0
        # rx.foreach bool flags
        r["rs_positive"] = r["rs"] > 1.0
        r["dc_good"] = r["downside_capture"] is not None and r["downside_capture"] < 80.0

    return top
