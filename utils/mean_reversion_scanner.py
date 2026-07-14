"""
역발상 과매도 스캐너 (Mean Reversion / Oversold Scanner)

전략: RSI14 < max_rsi AND 종가 < 볼린저밴드 하단(20일 2σ)을 동시에 만족하는
극단적 과매도 종목 탐색. 공포 구간 역발상 매수 후보 발굴에 특화.

필터:
  1. RSI14 < max_rsi (기본 30) — 과매도 임계값
  2. 종가 < BB하단(20일, 2σ) — 통계적 극단 이탈
정렬: 과매도 복합 점수 (RSI 컴포넌트 + BB 이탈 폭) 내림차순
"""

import concurrent.futures as cf
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import pandas as pd

from utils.stock_scanner import ScanResults


def _calc_mr(args: tuple) -> "dict | None":
    """단일 종목의 역발상 과매도 조건을 계산. 통과 시 dict 반환."""
    code, name, mktcap_eok, is_us, max_rsi = args
    try:
        end   = datetime.today()
        start = end - timedelta(days=90)

        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Volume"] > 0].dropna(subset=["Close"])
        if len(df) < 35:
            return None

        close     = df["Close"]
        close_now = float(close.iloc[-1])

        # ── RSI14 ────────────────────────────────────────────────
        delta    = close.diff()
        avg_gain = float(delta.clip(lower=0).rolling(14).mean().iloc[-1])
        avg_loss = float((-delta.clip(upper=0)).rolling(14).mean().iloc[-1])
        if pd.isna(avg_gain) or pd.isna(avg_loss):
            return None
        rsi = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
        if rsi >= max_rsi:
            return None

        # ── Bollinger Band (20일, 2σ) ────────────────────────────
        bb_mid   = float(close.rolling(20).mean().iloc[-1])
        bb_std   = float(close.rolling(20).std(ddof=1).iloc[-1])
        bb_lower = bb_mid - 2.0 * bb_std
        bb_upper = bb_mid + 2.0 * bb_std
        if pd.isna(bb_mid) or pd.isna(bb_std) or bb_lower <= 0:
            return None
        if close_now >= bb_lower:
            return None                 # BB 하단 이탈 필수

        bb_gap_pct = (close_now - bb_lower) / bb_lower * 100  # 음수: 얼마나 아래

        # ── 거래량비 (5일 / 20일 평균) ──────────────────────────
        vol_5d    = float(df["Volume"].tail(5).mean())
        vol_20d   = float(df["Volume"].tail(20).mean())
        vol_ratio = round(vol_5d / vol_20d, 2) if vol_20d > 0 else 1.0

        # ── 기간 수익률 ──────────────────────────────────────────
        ret_1w = ((close_now - float(close.iloc[-5]))  / float(close.iloc[-5])  * 100
                  if len(df) >= 5  else None)
        ret_1m = ((close_now - float(close.iloc[-20])) / float(close.iloc[-20]) * 100
                  if len(df) >= 20 else None)

        # ── 과매도 복합 점수 (0–100) ─────────────────────────────
        # RSI: 임계값보다 많이 낮을수록 높은 점수 (최대 50)
        rsi_score = max(0.0, (max_rsi - rsi) / max_rsi * 50.0)
        # BB 이탈 폭: 하단 대비 낙폭 1%당 5점 (최대 50)
        bb_score  = min(50.0, abs(bb_gap_pct) * 5.0)
        score     = round(rsi_score + bb_score, 1)

        return {
            "code":       code,
            "name":       name,
            "close":      close_now,
            "rsi14":      round(rsi, 1),
            "bb_lower":   round(bb_lower, 2),
            "bb_mid":     round(bb_mid, 2),
            "bb_upper":   round(bb_upper, 2),
            "bb_gap_pct": round(bb_gap_pct, 2),
            "vol_ratio":  vol_ratio,
            "ret_1w":     round(ret_1w, 2) if ret_1w is not None else None,
            "ret_1m":     round(ret_1m, 2) if ret_1m is not None else None,
            "score":      score,
            "mktcap_eok": mktcap_eok,
            "is_us":      is_us,
        }
    except Exception:
        return None


def scan_mean_reversion(
    market: str = "KOSPI",
    min_mktcap_eok: int = 3_000,
    max_rsi: float = 30.0,
    top_n: int = 30,
    max_universe: int = 150,
    _timeout_s: float = 90,
) -> "ScanResults":
    """RSI + 볼린저밴드 하단 이탈 역발상 과매도 종목 탐색.

    Args:
        market:          "KOSPI" | "KOSDAQ" | "SP500"
        min_mktcap_eok:  최소 시가총액 (억원, KR 전용)
        max_rsi:         RSI14 상한 (이 값 미만이어야 통과)
        top_n:           결과 최대 수
        max_universe:    시총 상위 N개로 사전 제한
        _timeout_s:      전체 타임아웃(초)
    Returns:
        ScanResults — 과매도 점수 내림차순 정렬.
    """
    is_us = market not in ("KOSPI", "KOSDAQ")

    # ── 종목 리스트 ──────────────────────────────────────────────
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
            sp500    = fdr.StockListing("S&P500")
            code_col = "Symbol" if "Symbol" in sp500.columns else sp500.columns[0]
            name_col = "Name"   if "Name"   in sp500.columns else sp500.columns[1]
            codes    = sp500[code_col].dropna().tolist()
            if max_universe > 0:
                codes = codes[:max_universe]
            names = dict(zip(sp500[code_col], sp500[name_col]))
            caps  = {}
        except Exception:
            return ScanResults(warning="S&P500 종목 목록을 불러오지 못했습니다.")

    args_list = [
        (c, names.get(c, c), caps.get(c, 0.0), is_us, max_rsi)
        for c in codes
    ]
    total = len(args_list)

    # ── 병렬 수집 ─────────────────────────────────────────────
    import time as _time
    executor  = ThreadPoolExecutor(max_workers=10)
    futures   = [executor.submit(_calc_mr, a) for a in args_list]
    deadline  = _time.monotonic() + _timeout_s

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
            if _time.monotonic() >= deadline:
                timed_out = total - completed
                break
    except cf.TimeoutError:
        timed_out = total - completed
    executor.shutdown(wait=False)

    warn = (f"⏱ {timed_out}개 종목이 {int(_timeout_s)}초 내 응답하지 않아 제외됨"
            if timed_out > 0 else "")

    # ── 점수 내림차순 → 상위 top_n ──────────────────────────────
    raw.sort(key=lambda x: x["score"], reverse=True)
    top = raw[:top_n]

    # ── 표시용 필드 추가 ─────────────────────────────────────────
    for i, r in enumerate(top):
        r["rank"] = i + 1
        c   = r["close"]
        cap = r.get("mktcap_eok", 0)
        r["close_str"]     = f"{c:,.0f}" if c >= 1 else f"{c:.2f}"
        r["mktcap_str"]    = (f"{cap/10000:.1f}조" if cap >= 10_000
                               else f"{cap:,.0f}억" if cap > 0 else "-")
        r["rsi_str"]       = f"{r['rsi14']:.1f}"
        r["bb_gap_str"]    = f"{r['bb_gap_pct']:+.2f}%"
        r["vol_ratio_str"] = f"{r['vol_ratio']:.2f}x"
        r["ret_1w_str"]    = (f"{r['ret_1w']:+.2f}%" if r["ret_1w"] is not None else "-")
        r["ret_1m_str"]    = (f"{r['ret_1m']:+.2f}%" if r["ret_1m"] is not None else "-")
        r["score_str"]     = f"{r['score']:.1f}"
        # bool flags (rx.foreach 내 비교 불가 우회)
        r["rsi_extreme"]   = r["rsi14"] < 20.0          # 극단적 공포 (RSI<20)
        r["vol_up"]        = r["vol_ratio"] >= 1.5       # 패닉 셀링 거래량
        r["ret_1w_neg"]    = r["ret_1w"] is None or r["ret_1w"] < 0
        r["ret_1m_pos"]    = r["ret_1m"] is not None and r["ret_1m"] > 0
        r["score_high"]    = r["score"] >= 50.0          # 고점수 강조

    return ScanResults(top, warning=warn)
