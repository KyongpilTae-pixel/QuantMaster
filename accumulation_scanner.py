"""세력 매집 / 숏커버링 스캐너."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import numpy as np
import pandas as pd

from utils.data_loader import QuantDataLoader
from utils.accumulation_indicators import (
    analyze_whale_with_options,
    compute_threshold,
    DEFAULT_OBV_MULTIPLIER,
    DEFAULT_ALPHA_MOMENTUM_THRESHOLD,
)

_INDEX_FDR = {
    "KOSPI":  "KS11",
    "KOSDAQ": "KQ11",
    "SP500":  "^GSPC",
    "NASDAQ": "^IXIC",
}

_US_MARKETS = {"SP500", "NASDAQ"}

# 점진적 완화 단계: (라벨, OBV배수, Alpha모멘텀임계값, signal_window)
_RELAXATION_STEPS = [
    ("원본",   2.0, 0.020, 15),
    ("2단계",  1.8, 0.018, 17),
    ("3단계",  1.6, 0.016, 19),
    ("4단계",  1.5, 0.014, 21),
    ("5단계",  1.3, 0.012, 23),
    ("6단계",  1.2, 0.010, 25),
    ("7단계",  1.1, 0.008, 30),
]

# 종목 1개당 최대 대기 시간 (초) — 네트워크 행 방지
_PER_STOCK_TIMEOUT = 15.0


def _fetch_us_short(symbol: str, n: int) -> pd.Series | None:
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info
        cur = info.get("sharesShort")
        prev = info.get("sharesShortPriorMonth")
        if not cur or not prev:
            return None
        idx = pd.bdate_range(end=datetime.today(), periods=n)
        return pd.Series(np.linspace(prev, cur, n), index=idx, name="Short_Balance")
    except Exception:
        return None


class AccumulationScanner:
    """세력 매집 / 숏커버링 스캐너 (점진적 완화 + 타임아웃)."""

    # ------------------------------------------------------------------
    # 공통 초기화 (State에서 단계별 호출 전 1회 실행)
    # ------------------------------------------------------------------

    def prepare(
        self,
        market: str,
        use_alpha: bool = True,
        use_short_filter: bool = True,
        lookback_days: int = 60,
        max_stocks: int = 80,
    ) -> dict:
        """
        데이터 로드 등 공통 초기화.

        Returns
        -------
        dict with keys: symbols, names, index_df, loader,
                        has_short, threshold, is_us, workers, market
        """
        is_us = market in _US_MARKETS
        has_short = use_short_filter and is_us
        threshold = compute_threshold(use_alpha, has_short)

        loader = QuantDataLoader()
        snapshot = loader.get_market_snapshot(market=market, max_pages=4)
        if snapshot.empty:
            return {}

        symbols = snapshot["Symbol"].dropna().tolist()[:max_stocks]
        names = dict(zip(snapshot["Symbol"], snapshot["Name"]))

        end = datetime.today()
        start = end - timedelta(days=lookback_days + 40)
        index_df = pd.DataFrame()
        try:
            idx_sym = _INDEX_FDR.get(market, "KS11")
            index_df = fdr.DataReader(
                idx_sym,
                start.strftime("%Y-%m-%d"),
                end.strftime("%Y-%m-%d"),
            )
        except Exception:
            pass

        return {
            "symbols": symbols,
            "names": names,
            "index_df": index_df,
            "loader": loader,
            "has_short": has_short,
            "use_alpha": use_alpha,
            "threshold": threshold,
            "is_us": is_us,
            "workers": 8 if is_us else 4,
            "market": market,
            "lookback_days": lookback_days,
        }

    # ------------------------------------------------------------------
    # 단계별 배치 스캔 (타임아웃 지원)
    # ------------------------------------------------------------------

    def _scan_batch(
        self,
        symbols: list[str],
        ctx: dict,
        use_alpha: bool,
        obv_mult: float,
        alpha_thresh: float,
        sig_win: int,
        step_label: str,
        step_timeout: float,
    ) -> list[dict]:
        """
        지정 파라미터로 종목 배치 스캔.

        Parameters
        ----------
        step_timeout : 이 배치 전체의 최대 대기 시간 (초). 초과 시 완료된 것만 반환.
        """
        loader = ctx["loader"]
        index_df = ctx["index_df"]
        names = ctx["names"]
        has_short = ctx["has_short"]
        threshold = ctx["threshold"]
        market = ctx["market"]
        workers = ctx["workers"]
        lookback_days = ctx["lookback_days"]

        def _process(
            symbol: str,
            _obv=obv_mult,
            _alpha=alpha_thresh,
            _win=sig_win,
            _step=step_label,
        ) -> dict | None:
            try:
                df = loader.get_ohlcv(symbol, lookback_days=lookback_days + 40)
                if len(df) < 25:
                    return None

                if has_short:
                    sb = _fetch_us_short(symbol, len(df))
                    if sb is not None:
                        df = df.copy()
                        df["Short_Balance"] = sb.reindex(df.index, method="ffill")

                full_df, _ = analyze_whale_with_options(
                    df, index_df,
                    use_alpha=use_alpha,
                    use_short_filter=has_short,
                    threshold=threshold,
                    obv_multiplier=_obv,
                    alpha_momentum_threshold=_alpha,
                )

                recent = full_df.tail(_win)
                max_score = int(recent["Accum_Score"].max())
                if max_score < threshold:
                    return None

                sig_idx = recent["Accum_Score"].idxmax()
                sig_row = full_df.loc[sig_idx]
                latest = full_df.iloc[-1]

                vol_ma20 = full_df["Volume"].rolling(20).mean().iloc[-1]
                vol_ratio = (
                    round(float(latest["Volume"]) / vol_ma20, 2) if vol_ma20 > 0 else 0.0
                )

                tags = []
                if sig_row.get("Is_Whale_Spike", False):
                    tags.append("매집봉")
                if sig_row.get("Alpha_Sig", 0):
                    tags.append("알파")
                if sig_row.get("Short_Sig", 0):
                    tags.append("숏커버")

                return {
                    "Name": names.get(symbol, symbol),
                    "Symbol": symbol,
                    "Market": market,
                    "Signal_Date": str(sig_idx.date()),
                    "Score": max_score,
                    "Signal_Type": "+".join(tags) if tags else "-",
                    "OBV_Spike": bool(sig_row.get("Is_Whale_Spike", False)),
                    "Alpha": bool(sig_row.get("Alpha_Sig", 0)),
                    "Short_Cover": bool(sig_row.get("Short_Sig", 0)),
                    "Close": round(float(latest["Close"]), 0),
                    "Volume_Ratio": vol_ratio,
                    "Applied_Step": _step,
                }
            except Exception:
                return None

        results = []
        # 종목별 타임아웃: 전체 step_timeout과 _PER_STOCK_TIMEOUT 중 작은 값
        per_future = min(_PER_STOCK_TIMEOUT, step_timeout)

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_process, s): s for s in symbols}
            deadline = time.monotonic() + step_timeout
            try:
                for f in as_completed(futures, timeout=step_timeout):
                    try:
                        r = f.result(timeout=per_future)
                        if r:
                            results.append(r)
                    except Exception:
                        pass
                    # 개별 future 완료 후에도 deadline 재확인
                    if time.monotonic() > deadline:
                        break
            except FuturesTimeout:
                # step_timeout 초과 — 완료된 것만 사용, 나머지 취소
                for f in futures:
                    f.cancel()

        return results

    # ------------------------------------------------------------------
    # 전체 스캔 (편의용 — 타임아웃 없는 단순 호출)
    # ------------------------------------------------------------------

    def run_scan(
        self,
        market: str = "KOSPI",
        use_alpha: bool = True,
        use_short_filter: bool = True,
        lookback_days: int = 60,
        max_stocks: int = 80,
        top_n: int = 10,
        max_seconds: float = 300.0,
    ) -> pd.DataFrame:
        """
        세력 매집 스캔 (점진적 완화). State에서 직접 단계 루프를 돌 수 없을 때 사용.
        """
        ctx = self.prepare(market, use_alpha, use_short_filter, lookback_days, max_stocks)
        if not ctx:
            return pd.DataFrame()

        found: dict[str, dict] = {}
        remaining = list(ctx["symbols"])
        start = time.monotonic()
        n_steps = len(_RELAXATION_STEPS)

        for step_idx, (step_label, obv_mult, alpha_thresh, sig_win) in enumerate(_RELAXATION_STEPS):
            if len(found) >= top_n or not remaining:
                break
            elapsed = time.monotonic() - start
            if elapsed >= max_seconds:
                break
            remain = max_seconds - elapsed
            step_timeout = remain / max(1, n_steps - step_idx)

            new = self._scan_batch(
                remaining, ctx, use_alpha,
                obv_mult, alpha_thresh, sig_win, step_label, step_timeout,
            )
            for r in new:
                found.setdefault(r["Symbol"], r)
            remaining = [s for s in remaining if s not in found]
            if len(found) >= top_n:
                break

        if not found:
            return pd.DataFrame()

        return (
            pd.DataFrame(found.values())
            .sort_values("Score", ascending=False)
            .head(top_n)
            .reset_index(drop=True)
        )
