"""
Magic Formula 스캐너 (Greenblatt, 2005)

전략: EBIT/EV 순위 + ROIC 순위 → 합산 순위 낮을수록 '고수익+저평가' 종목.
  - EBIT/EV : 수익률 척도 (Earnings Yield)
  - ROIC    : 자본 효율성 척도

수식:
  EV      = 시가총액 + 총부채 - 현금성자산
  ROIC    = EBIT / (순운전자본 + 순고정자산)
             순운전자본 = 유동자산 - 유동부채 (최소 0)
             순고정자산 = 유형자산 순액

필터:
  - 시가총액 ≥ min_mktcap
  - EBIT > 0 (수익성 기본 조건)
  - EV > 0
  - ROIC > 0
"""

import concurrent.futures as cf
from concurrent.futures import ThreadPoolExecutor

import FinanceDataReader as fdr
import yfinance as yf
import pandas as pd


def _yf_symbol(code: str, market: str) -> str:
    if market in ("KOSPI", "KOSDAQ"):
        return code + (".KS" if market == "KOSPI" else ".KQ")
    return code


def _get(df, keys: list[str], col: int = 0):
    for k in keys:
        if k in df.index:
            vals = df.loc[k].dropna()
            if len(vals) > col:
                try:
                    return float(vals.iloc[col])
                except (TypeError, ValueError):
                    pass
    return None


def _calc_magic(args: tuple) -> "dict | None":
    """단일 종목의 Magic Formula 지표 계산. 조건 미충족 시 None."""
    code, name, mktcap_raw, is_us, market = args
    try:
        yf_sym = _yf_symbol(code, market)
        ticker = yf.Ticker(yf_sym)
        info   = ticker.info or {}
        fin    = ticker.financials
        cf_    = ticker.cashflow
        bs     = ticker.balance_sheet

        if fin is None or fin.empty:
            return None

        # ── EBIT ─────────────────────────────────────────────────────────
        ebit = _get(fin, ["EBIT", "Operating Income",
                           "Normalized EBITDA"])   # EBITDA 없으면 대체
        if ebit is None or ebit <= 0:
            return None

        # ── EV 계산 ───────────────────────────────────────────────────────
        mktcap     = info.get("marketCap") or mktcap_raw
        total_debt = info.get("totalDebt")
        cash       = info.get("totalCash") or info.get("cash")

        if total_debt is None and bs is not None and not bs.empty:
            lt = _get(bs, ["Long Term Debt", "Long-Term Debt"])
            st = _get(bs, ["Current Debt", "Short Term Debt"])
            total_debt = (lt or 0) + (st or 0)
        if cash is None and bs is not None and not bs.empty:
            cash = _get(bs, ["Cash And Cash Equivalents",
                              "Cash Cash Equivalents And Short Term Investments"])

        if mktcap is None or mktcap <= 0:
            return None
        ev = mktcap + (total_debt or 0) - (cash or 0)
        if ev <= 0:
            return None

        # ── ROIC 계산 ─────────────────────────────────────────────────────
        # 순운전자본 = max(0, 유동자산 - 유동부채)
        nwc = 0.0
        if bs is not None and not bs.empty:
            curr_assets = _get(bs, ["Current Assets", "Total Current Assets"])
            curr_liab   = _get(bs, ["Current Liabilities", "Total Current Liabilities"])
            if curr_assets is not None and curr_liab is not None:
                nwc = max(0.0, curr_assets - curr_liab)

        # 순고정자산 = 유형자산 순액
        net_ppe = 0.0
        if bs is not None and not bs.empty:
            ppe = _get(bs, ["Net PPE", "Property Plant Equipment Net",
                             "Net Property Plant And Equipment"])
            if ppe is not None:
                net_ppe = max(0.0, ppe)

        invested_capital = nwc + net_ppe
        if invested_capital <= 0:
            return None
        roic = ebit / invested_capital

        # ── 수익률 지표 (Earnings Yield = EBIT/EV) ────────────────────────
        earnings_yield = ebit / ev

        # ── 현재가 ────────────────────────────────────────────────────────
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
            try:
                hist = ticker.history(period="5d")
                price = float(hist["Close"].iloc[-1]) if not hist.empty else None
            except Exception:
                price = None

        # ── 단위 변환 ─────────────────────────────────────────────────────
        div = 1e9 if is_us else 1e8
        unit = "$B" if is_us else "억원"

        return {
            "code":            code,
            "name":            name,
            "market":          market,
            "is_us":           is_us,
            "mktcap_raw":      mktcap,
            "ev_raw":          ev,
            "ebit_raw":        ebit,
            "roic_raw":        roic,
            "earnings_yield":  earnings_yield,   # EBIT/EV (높을수록 좋음)
            "roic":            roic,             # (높을수록 좋음)
            "mktcap_str":      f"{mktcap/div:.1f}{unit}",
            "ev_str":          f"{ev/div:.1f}{unit}",
            "ebit_str":        f"{ebit/div:.1f}{unit}",
            "ey_str":          f"{earnings_yield*100:.1f}%",
            "roic_str":        f"{roic*100:.1f}%",
            "price":           price,
            "price_str":       (f"${price:,.2f}" if is_us else f"{price:,.0f}") if price else "-",
        }
    except Exception:
        return None


def scan_magic_formula(
    market: str = "KOSPI",
    min_mktcap_eok: int = 3_000,
    top_n: int = 30,
    max_universe: int = 150,
    _timeout_s: float = 120,
) -> dict:
    """
    Magic Formula 스캐너.

    Args:
        market:          "KOSPI" | "KOSDAQ" | "SP500"
        min_mktcap_eok:  최소 시가총액 (억원, KR 전용; US는 무시)
        top_n:           최종 결과 수
        max_universe:    시총 상위 N개로 사전 제한
        _timeout_s:      전체 타임아웃(초)
    Returns:
        {"results": List[dict], "warning": str, "count_scanned": int}
    """
    import time as _time
    is_us = market not in ("KOSPI", "KOSDAQ")

    # ── 종목 리스트 ─────────────────────────────────────────────────────
    if not is_us:
        from utils.data_loader import fetch_kr_stock_listing
        listing = fetch_kr_stock_listing(market, min_mktcap_eok)
        if listing.empty:
            return {"results": [], "warning": "종목 목록을 불러오지 못했습니다.", "count_scanned": 0}

        cols = {c.lower(): c for c in listing.columns}
        code_col = cols.get("code") or cols.get("symbol", listing.columns[0])
        name_col = cols.get("name", listing.columns[1])
        cap_col  = cols.get("marcap") or cols.get("marketcap")

        if cap_col and min_mktcap_eok > 0:
            listing = listing[listing[cap_col].fillna(0) >= min_mktcap_eok * 1e8]
        if listing.empty:
            return {"results": [], "warning": "시가총액 조건 미충족.", "count_scanned": 0}
        if max_universe > 0:
            listing = listing.head(max_universe)

        codes  = listing[code_col].tolist()
        names  = dict(zip(listing[code_col], listing[name_col]))
        caps   = ({row[code_col]: float(row[cap_col])
                   for _, row in listing.iterrows()} if cap_col else {})
    else:
        try:
            sp500    = fdr.StockListing("S&P500")
            code_col = "Symbol" if "Symbol" in sp500.columns else sp500.columns[0]
            name_col = "Name"   if "Name"   in sp500.columns else sp500.columns[1]
            codes    = sp500[code_col].dropna().tolist()
            if max_universe > 0:
                codes = codes[:max_universe]
            names = dict(zip(sp500[code_col], sp500[name_col]))
            caps  = {}
        except Exception:
            return {"results": [], "warning": "S&P500 목록 오류.", "count_scanned": 0}

    args_list = [
        (c, names.get(c, c), caps.get(c, 0.0), is_us, market)
        for c in codes
    ]
    total = len(args_list)

    # ── 병렬 수집 ───────────────────────────────────────────────────────
    executor = ThreadPoolExecutor(max_workers=8)
    futures  = [executor.submit(_calc_magic, a) for a in args_list]
    deadline = _time.monotonic() + _timeout_s

    raw: list[dict] = []
    completed = 0
    timed_out = 0
    try:
        for f in cf.as_completed(futures, timeout=_timeout_s):
            try:
                r = f.result(timeout=0)
                if r:
                    raw.append(r)
            except Exception:
                pass
            completed += 1
            if _time.monotonic() >= deadline:
                timed_out = total - completed
                break
    except cf.TimeoutError:
        timed_out = total - completed
    executor.shutdown(wait=False)

    warn = (f"⏱ {timed_out}개 종목이 {int(_timeout_s)}초 내 응답하지 않아 제외됨"
            if timed_out > 0 else "")

    if not raw:
        return {"results": [], "warning": warn or "조건 충족 종목 없음.", "count_scanned": completed}

    # ── Magic Formula 순위 계산 ─────────────────────────────────────────
    # 1) EBIT/EV 높은 순서로 순위 부여 (1=가장 저평가)
    raw.sort(key=lambda x: x["earnings_yield"], reverse=True)
    for i, r in enumerate(raw):
        r["ey_rank"] = i + 1

    # 2) ROIC 높은 순서로 순위 부여 (1=가장 고효율)
    raw.sort(key=lambda x: x["roic"], reverse=True)
    for i, r in enumerate(raw):
        r["roic_rank"] = i + 1

    # 3) 합산 순위 낮은 순으로 정렬 → 최종 순위
    raw.sort(key=lambda x: x["ey_rank"] + x["roic_rank"])
    top = raw[:top_n]

    # ── 표시용 필드 추가 ─────────────────────────────────────────────────
    for i, r in enumerate(top):
        combined = r["ey_rank"] + r["roic_rank"]
        r["rank"]         = i + 1
        r["combined_rank"] = combined
        r["combined_str"]  = str(combined)
        r["ey_rank_str"]   = str(r["ey_rank"])
        r["roic_rank_str"] = str(r["roic_rank"])
        # bool 플래그
        r["ey_top"]        = r["ey_rank"]   <= len(raw) // 4   # 상위 25%
        r["roic_top"]      = r["roic_rank"] <= len(raw) // 4

    return {"results": top, "warning": warn, "count_scanned": completed}
