"""
눌림목 스캐너 (Pullback in Uptrend Scanner)

전략: 중장기 상승추세가 유지되는 종목 중 단기 급락(1주 -3% ~ -25%)으로
과매도 상태에 진입한 종목 탐색.

필터 조합:
  1. 현재가 > SMA60  (상승추세 확인)
  2. 3M 수익률 > 0%  (중기 모멘텀 양수)
  3. 1W 수익률 ∈ (min_dip_1w, -25%)  (단기 급락 범위)
  4. RSI14 < max_rsi  (단기 과매도)
정렬: 3M 수익률 내림차순 (추세 강도 높은 종목 상단)
"""

import concurrent.futures as cf
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

from utils.stock_scanner import ScanResults

# 상수
_MAX_DIP_1W = -25.0  # 1주 최대 낙폭 (이보다 많이 빠지면 추세 이탈로 판단)


def _calc_pullback(args: tuple) -> "dict | None":
    """단일 종목의 눌림목 조건을 계산하고 필터 통과 시 dict 반환."""
    code, name, mktcap_eok, is_us, min_dip_1w, max_rsi, min_trend_3m = args
    try:
        end   = datetime.today()
        start = end - timedelta(days=150)  # SMA60(60일) + 여유 90일

        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Volume"] > 0].dropna(subset=["Close"])

        if len(df) < 65:  # SMA60 + 5일 최소 필요
            return None

        close = df["Close"]
        high  = df["High"]
        close_now = float(close.iloc[-1])

        # ── 필터 1: 현재가 > SMA60 (상승추세) ──────────────────────
        sma60 = float(close.rolling(60).mean().iloc[-1])
        if pd.isna(sma60) or close_now <= sma60:
            return None

        # ── 필터 2: 3M 수익률 > 0 (중기 모멘텀) ────────────────────
        ret_3m = (close_now - float(close.iloc[-60])) / float(close.iloc[-60]) * 100
        if ret_3m < min_trend_3m:
            return None

        # ── 필터 3: 1W 수익률 ∈ (min_dip_1w, _MAX_DIP_1W) ─────────
        if len(df) < 5:
            return None
        ret_1w = (close_now - float(close.iloc[-5])) / float(close.iloc[-5]) * 100
        if ret_1w >= min_dip_1w or ret_1w <= _MAX_DIP_1W:
            return None

        # ── 필터 4: RSI14 < max_rsi (단기 과매도) ───────────────────
        delta    = close.diff()
        gain     = delta.clip(lower=0)
        loss     = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean().iloc[-1]
        avg_loss = loss.rolling(14).mean().iloc[-1]
        if pd.isna(avg_gain) or pd.isna(avg_loss):
            return None
        rsi = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
        if rsi >= max_rsi:
            return None

        # ── 부가 지표 ────────────────────────────────────────────────
        ret_1m = ((close_now - float(close.iloc[-20])) / float(close.iloc[-20]) * 100
                  if len(df) >= 20 else None)

        # 20일 고점 대비 현재 낙폭
        high_20d = float(high.tail(20).max())
        drawdown_20d = (close_now - high_20d) / high_20d * 100

        # SMA60 대비 괴리율 (얼마나 추세선 위에 있는가)
        sma60_gap = (close_now - sma60) / sma60 * 100

        # 거래량비 (최근 5일 / 20일 평균)
        vol_5d  = float(df["Volume"].tail(5).mean())
        vol_20d = float(df["Volume"].tail(20).mean())
        vol_ratio = round(vol_5d / vol_20d, 2) if vol_20d > 0 else 1.0

        return {
            "code":         code,
            "name":         name,
            "close":        close_now,
            "ret_1w":       round(ret_1w, 2),
            "ret_1m":       round(ret_1m, 2) if ret_1m is not None else None,
            "ret_3m":       round(ret_3m, 2),
            "drawdown_20d": round(drawdown_20d, 2),
            "sma60_gap":    round(sma60_gap, 2),
            "rsi14":        round(rsi, 1),
            "vol_ratio":    vol_ratio,
            "mktcap_eok":   mktcap_eok,
            "is_us":        is_us,
        }
    except Exception:
        return None


def scan_pullback_stocks(
    market: str = "KOSPI",
    min_mktcap_eok: int = 3_000,
    min_dip_1w: float = -5.0,
    max_rsi: float = 45.0,
    min_trend_3m: float = 0.0,
    top_n: int = 30,
    max_universe: int = 150,
    _timeout_s: float = 90,
    progress_fn=None,
) -> "ScanResults":
    """상승추세를 유지하면서 단기 급락한 눌림목 종목 탐색.

    Args:
        market: "KOSPI" | "KOSDAQ" | "SP500"
        min_mktcap_eok: 최소 시가총액 (억원, KR만 적용)
        min_dip_1w: 1주 낙폭 하한 (이 값 이하여야 통과, 음수). 예: -5.0 → -5% 이상 하락한 종목만
        max_rsi: RSI14 상한 (이 값 미만이어야 통과)
        min_trend_3m: 3M 수익률 최솟값 (기본 0% — 양수 추세만)
        top_n: 결과 최대 수
        max_universe: 시총 상위 N개로 사전 제한 (속도 최적화)
        _timeout_s: 전체 타임아웃(초)
    Returns:
        ScanResults — 3M 수익률 내림차순 정렬.
    """
    is_us = market not in ("KOSPI", "KOSDAQ")

    # ── 종목 리스트 ──────────────────────────────────────────────────
    if not is_us:
        from utils.data_loader import fetch_kr_stock_listing
        listing = fetch_kr_stock_listing(market, min_mktcap_eok)
        if listing.empty:
            return ScanResults(warning="종목 목록을 불러오지 못했습니다.")

        cols_lower = {c.lower(): c for c in listing.columns}
        code_col = cols_lower.get("code") or cols_lower.get("symbol", listing.columns[0])
        name_col = cols_lower.get("name", listing.columns[1])
        cap_col  = cols_lower.get("marcap") or cols_lower.get("marketcap")

        if cap_col and min_mktcap_eok > 0:
            listing = listing[listing[cap_col].fillna(0) >= min_mktcap_eok * 1e8]
        if listing.empty:
            return ScanResults(warning="시가총액 조건을 만족하는 종목이 없습니다.")

        if max_universe > 0:
            listing = listing.head(max_universe)

        codes = listing[code_col].tolist()
        names = dict(zip(listing[code_col], listing[name_col]))
        caps: dict = {}
        if cap_col:
            for _, row in listing.iterrows():
                caps[row[code_col]] = round(float(row[cap_col]) / 1e8, 0)
    else:
        try:
            sp500 = fdr.StockListing("S&P500")
            code_col = "Symbol" if "Symbol" in sp500.columns else sp500.columns[0]
            name_col = "Name"   if "Name"   in sp500.columns else sp500.columns[1]
            codes = sp500[code_col].dropna().tolist()
            if max_universe > 0:
                codes = codes[:max_universe]
            names = dict(zip(sp500[code_col], sp500[name_col]))
            caps = {}
        except Exception:
            return ScanResults(warning="S&P500 종목 목록을 불러오지 못했습니다.")

    args_list = [
        (c, names.get(c, c), caps.get(c, 0.0), is_us,
         min_dip_1w, max_rsi, min_trend_3m)
        for c in codes
    ]
    total = len(args_list)
    if progress_fn:
        progress_fn(0, total)

    # ── 병렬 수집 ─────────────────────────────────────────────────
    import time as _time
    executor = ThreadPoolExecutor(max_workers=10)
    futures  = [executor.submit(_calc_pullback, a) for a in args_list]
    deadline = _time.monotonic() + _timeout_s

    raw: list[dict] = []
    completed = 0
    timed_out = 0
    try:
        for f in cf.as_completed(futures, timeout=_timeout_s):
            try:
                result = f.result(timeout=0)
                if result:
                    raw.append(result)
            except Exception:
                pass
            completed += 1
            if progress_fn:
                progress_fn(completed, total)
            if _time.monotonic() >= deadline:
                timed_out = total - completed
                break
    except cf.TimeoutError:
        timed_out = total - completed
    executor.shutdown(wait=False)

    warn = (f"⏱ {timed_out}개 종목이 {int(_timeout_s)}초 내 응답하지 않아 제외됨"
            if timed_out > 0 else "")

    # ── 3M 수익률 내림차순 정렬 → 상위 top_n ───────────────────────
    raw.sort(key=lambda x: x["ret_3m"], reverse=True)
    top = raw[:top_n]

    # ── 표시용 필드 추가 ──────────────────────────────────────────
    for i, r in enumerate(top):
        r["rank"] = i + 1
        c   = r["close"]
        cap = r.get("mktcap_eok", 0)
        r["close_str"]    = f"{c:,.0f}" if c >= 1 else f"{c:.2f}"
        r["mktcap_str"]   = (f"{cap/10000:.1f}조" if cap >= 10_000
                              else f"{cap:,.0f}억" if cap > 0 else "-")
        r["ret_1w_str"]   = f"{r['ret_1w']:+.2f}%"
        r["ret_1m_str"]   = (f"{r['ret_1m']:+.2f}%" if r["ret_1m"] is not None else "-")
        r["ret_3m_str"]   = f"{r['ret_3m']:+.2f}%"
        r["drawdown_str"] = f"{r['drawdown_20d']:+.2f}%"
        r["sma60_gap_str"]= f"{r['sma60_gap']:+.2f}%"
        r["rsi_str"]      = f"{r['rsi14']:.1f}"
        r["vol_ratio_str"]= f"{r['vol_ratio']:.2f}x"
        # bool flags (rx.foreach 내 비교 불가 우회)
        r["ret_1w_neg"]      = r["ret_1w"] < 0      # 항상 True지만 명시
        r["ret_1m_pos"]      = r["ret_1m"] is not None and r["ret_1m"] > 0
        r["ret_3m_pos"]      = r["ret_3m"] > 0
        r["drawdown_shallow"]= r["drawdown_20d"] >= -10.0  # -10% 이내 얕은 눌림
        r["rsi_strong"]      = r["rsi14"] < 35.0           # 강한 과매도 (강조 표시)
        r["vol_up"]          = r["vol_ratio"] >= 1.2

    return ScanResults(top, warning=warn)
