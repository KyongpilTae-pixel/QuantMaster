"""배당 성장 스크리닝 — KR(NAVER) + US(yfinance) 고배당·배당성장 필터."""

from __future__ import annotations

import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed

import FinanceDataReader as fdr
import pandas as pd
import yfinance as yf


def _us_dividend_info(symbol: str) -> dict | None:
    """yfinance로 미국 종목 배당 정보 수집."""
    try:
        t = yf.Ticker(symbol)
        info = t.info or {}
        div_yield = info.get("dividendYield") or 0.0
        if div_yield < 0.001:
            return None
        payout = info.get("payoutRatio") or None
        name = info.get("longName") or info.get("shortName") or symbol
        mktcap = info.get("marketCap") or 0
        price  = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0

        # 5년 배당 내역으로 성장 여부 확인
        hist = t.dividends
        div_growing = False
        if hist is not None and len(hist) >= 4:
            annual = hist.resample("YE").sum()
            if len(annual) >= 2:
                div_growing = bool(annual.iloc[-1] > annual.iloc[-2])

        return {
            "name":       name,
            "symbol":     symbol,
            "market":     "SP500",
            "price":      round(float(price), 2),
            "div_yield":  round(float(div_yield) * 100, 2),
            "payout_ratio": round(float(payout) * 100, 1) if payout else None,
            "div_growing": div_growing,
            "mktcap_b":   round(float(mktcap) / 1e9, 1) if mktcap else 0.0,
            "is_us":      True,
        }
    except Exception:
        return None


def scan_dividend_stocks(
    market: str = "KOSPI",
    min_yield_pct: float = 3.0,
    max_payout_pct: float = 70.0,
    top_n: int = 30,
) -> list[dict]:
    """
    배당 스크리닝.
      KR: NAVER 스냅샷 → 배당수익률 필터 (즉시)
      US: S&P500 종목 샘플 → yfinance 병렬 수집

    반환: list[dict] — name, symbol, market, price, div_yield, payout_ratio,
                        div_growing, mktcap_b, is_us
    """
    results: list[dict] = []

    if market in ("KOSPI", "KOSDAQ"):
        results = _scan_kr_dividend(market, min_yield_pct, max_payout_pct, top_n)
    elif market in ("SP500", "NASDAQ"):
        results = _scan_us_dividend(market, min_yield_pct, max_payout_pct, top_n)

    return results


def _scan_kr_dividend(
    market: str,
    min_yield_pct: float,
    max_payout_pct: float,
    top_n: int,
) -> list[dict]:
    from utils.data_loader import QuantDataLoader
    loader = QuantDataLoader()
    try:
        df = loader.get_market_snapshot(market=market)
    except Exception:
        return []
    if df.empty:
        return []

    needed = {"Name", "Symbol", "Close", "DivYield", "MarketCap", "PER"}
    if not needed.issubset(df.columns):
        return []

    df = df[df["DivYield"].notna() & (df["DivYield"] >= min_yield_pct)].copy()
    df = df.sort_values("DivYield", ascending=False).head(top_n)

    rows: list[dict] = []
    for _, row in df.iterrows():
        per = row.get("PER")
        # 간이 배당성향%: 배당금/EPS ≈ (div_yield%*price/100) / (price/PER) = div_yield%*PER/100*100 = div_yield%*PER
        payout = None
        if per and per > 0:
            payout = round(float(row["DivYield"]) * float(per), 1)

        mktcap_eok = row.get("MarketCap") or 0
        rows.append({
            "name":       str(row.get("Name", "")),
            "symbol":     str(row.get("Symbol", "")),
            "market":     market,
            "price":      float(row.get("Close", 0)),
            "div_yield":  round(float(row["DivYield"]), 2),
            "payout_ratio": payout,
            "div_growing": False,
            "mktcap_b":   round(float(mktcap_eok) / 10000, 1),  # 억→조
            "is_us":      False,
        })
    return rows


def _scan_us_dividend(
    market: str,
    min_yield_pct: float,
    max_payout_pct: float,
    top_n: int,
) -> list[dict]:
    # fdr.StockListing 타임아웃 처리
    try:
        with ThreadPoolExecutor(max_workers=1) as _ex:
            _f = _ex.submit(fdr.StockListing, "S&P500")
            df = _f.result(timeout=15)
        symbols = df["Symbol"].dropna().tolist()
    except Exception:
        return []

    # 최대 200개 샘플 병렬 수집 — 전체 배치 30초 상한
    sample = symbols[:200]
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_us_dividend_info, sym): sym for sym in sample}
        done, _ = concurrent.futures.wait(futures, timeout=30)
        for fut in done:
            try:
                r = fut.result()
            except Exception:
                continue
            if r and r["div_yield"] >= min_yield_pct:
                if r["payout_ratio"] is None or r["payout_ratio"] <= max_payout_pct:
                    results.append(r)

    results.sort(key=lambda x: x["div_yield"], reverse=True)
    return results[:top_n]
