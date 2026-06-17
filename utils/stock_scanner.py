"""
기간별 종목 모멘텀 스캐너.
삼성전기·LG이노텍 류 '꾸준한 강세주' 발굴.
당일 급등(세력 탐지)이 아닌 수주/수개월 상승 추세 종목 탐색.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

# 기간별 달력일 수 (여유분 포함)
_CALENDAR_DAYS: dict[str, int] = {
    "1W":  12,
    "1M":  35,
    "3M": 100,
}

# 기간별 거래일 수
_TRADE_DAYS: dict[str, int] = {
    "1W":  5,
    "1M": 20,
    "3M": 60,
}

PERIOD_LABELS: dict[str, str] = {
    "1W": "1주",
    "1M": "1개월",
    "3M": "3개월",
}


def _calc_stock(args: tuple) -> dict | None:
    """단일 종목 OHLCV에서 N일 수익률 + 거래량비를 계산."""
    code, name, mktcap_eok, period = args
    try:
        cal_days   = _CALENDAR_DAYS.get(period, _CALENDAR_DAYS["1M"])
        trade_days = _TRADE_DAYS.get(period, _TRADE_DAYS["1M"])
        end   = datetime.today()
        start = end - timedelta(days=cal_days + 30)

        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Volume"] > 0].dropna(subset=["Close"])

        if len(df) < max(trade_days, 20):
            return None

        close_now   = float(df["Close"].iloc[-1])
        close_start = float(df["Close"].iloc[-trade_days])
        if close_start == 0:
            return None
        ret = (close_now - close_start) / close_start * 100

        # 거래량 비율 (최근 5일 평균 / 20일 평균)
        vol_5d  = float(df["Volume"].tail(5).mean())
        vol_20d = float(df["Volume"].tail(20).mean())
        vol_ratio = round(vol_5d / vol_20d, 2) if vol_20d > 0 else 1.0

        # 1주 수익률 추가 컬럼 (1M/3M 기간일 때만)
        ret_1w = None
        if period in ("1M", "3M") and len(df) >= 5:
            c_1w = float(df["Close"].iloc[-5])
            if c_1w > 0:
                ret_1w = round((close_now - c_1w) / c_1w * 100, 2)

        return {
            "code":       code,
            "name":       name,
            "close":      close_now,
            "ret_pct":    round(ret, 2),
            "ret_1w":     ret_1w,
            "vol_ratio":  vol_ratio,
            "mktcap_eok": mktcap_eok,
        }
    except Exception:
        return None


def scan_stock_momentum(
    market: str = "KOSPI",
    period: str = "1M",
    min_mktcap_eok: int = 3_000,
    top_n: int = 30,
) -> list[dict]:
    """기간별 수익률 상위 종목 스캔 (꾸준한 강세주 발굴).

    Args:
        market: "KOSPI" | "KOSDAQ" | "SP500"
        period: "1W" | "1M" | "3M"
        min_mktcap_eok: 최소 시가총액 억원 단위 (KR). US는 S&P500 구성이므로 무시.
        top_n: 반환 최대 종목 수.
    Returns:
        rank·code·name·ret_pct·vol_ratio 등 bool 플래그 포함 dict 리스트.
    """
    if period not in _CALENDAR_DAYS:
        period = "1M"

    is_us = market not in ("KOSPI", "KOSDAQ")

    # ── 종목 리스트 ──────────────────────────────────────────────────
    if not is_us:
        from utils.data_loader import fetch_kr_stock_listing
        listing = fetch_kr_stock_listing(market, min_mktcap_eok)
        if listing.empty:
            return []

        cols_lower = {c.lower(): c for c in listing.columns}
        code_col = cols_lower.get("code") or cols_lower.get("symbol", listing.columns[0])
        name_col = cols_lower.get("name", listing.columns[1])
        cap_col  = cols_lower.get("marcap") or cols_lower.get("marketcap")

        if cap_col and min_mktcap_eok > 0:
            listing = listing[listing[cap_col].fillna(0) >= min_mktcap_eok * 1e8]
        if listing.empty:
            return []

        codes = listing[code_col].tolist()
        names = dict(zip(listing[code_col], listing[name_col]))
        caps: dict = {}
        if cap_col:
            for _, row in listing.iterrows():
                caps[row[code_col]] = round(float(row[cap_col]) / 1e8, 0)

    else:  # US — S&P500 구성 종목
        try:
            sp500 = fdr.StockListing("S&P500")
            code_col = "Symbol" if "Symbol" in sp500.columns else sp500.columns[0]
            name_col = "Name"   if "Name"   in sp500.columns else sp500.columns[1]
            codes = sp500[code_col].dropna().tolist()
            names = dict(zip(sp500[code_col], sp500[name_col]))
            caps = {}
        except Exception:
            return []

    args_list = [(c, names.get(c, c), caps.get(c, 0.0), period) for c in codes]

    with ThreadPoolExecutor(max_workers=15) as ex:
        raw = list(ex.map(_calc_stock, args_list))

    results = [r for r in raw if r is not None]
    results.sort(key=lambda x: x["ret_pct"], reverse=True)
    top = results[:top_n]

    for i, r in enumerate(top):
        r["rank"]  = i + 1
        r["is_us"] = is_us

        r["ret_str"]       = f"{r['ret_pct']:+.2f}%"
        r["ret_positive"]  = r["ret_pct"] > 0
        r["vol_ratio_str"] = f"{r['vol_ratio']:.2f}x"
        r["vol_up"]        = r["vol_ratio"] >= 1.2

        c = r["close"]
        r["close_str"] = f"{c:,.0f}" if c >= 1 else f"{c:.2f}"

        cap = r["mktcap_eok"]
        r["mktcap_str"] = (
            f"{cap/10000:.1f}조" if cap >= 10_000
            else f"{cap:,.0f}억"  if cap > 0
            else "-"
        )

        ret1w = r.get("ret_1w")
        r["ret_1w_str"]      = f"{ret1w:+.2f}%" if ret1w is not None else "-"
        r["ret_1w_positive"] = ret1w is not None and ret1w > 0
        r["has_ret_1w"]      = ret1w is not None

    return top
