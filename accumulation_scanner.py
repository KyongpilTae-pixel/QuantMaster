"""세력 매집 / 숏커버링 스캐너."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import numpy as np
import pandas as pd

from utils.data_loader import QuantDataLoader
from utils.accumulation_indicators import (
    analyze_whale_with_options,
    SIGNAL_THRESHOLD_KR,
    SIGNAL_THRESHOLD_US,
)

_INDEX_FDR = {
    "KOSPI":  "KS11",
    "KOSDAQ": "KQ11",
    "SP500":  "^GSPC",
    "NASDAQ": "^IXIC",
}

_US_MARKETS = {"SP500", "NASDAQ"}


def _fetch_us_short(symbol: str, n: int) -> pd.Series | None:
    """
    yfinance sharesShort / sharesShortPriorMonth 를
    n 영업일 선형 보간 시계열로 변환 (월별 데이터 근사).
    """
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
    def run_scan(
        self,
        market: str = "KOSPI",
        use_alpha: bool = True,
        use_short_filter: bool = True,
        lookback_days: int = 60,
        signal_window: int = 15,
        max_stocks: int = 80,
        top_n: int = 10,
    ) -> pd.DataFrame:
        """
        세력 매집 / 숏커버링 시그널 스캔.

        Parameters
        ----------
        market          : KOSPI / KOSDAQ / SP500 / NASDAQ
        use_alpha       : 지수 대비 상대강도 사용
        use_short_filter: 공매도 잔고 필터 (US만 실데이터, KR 자동 비활성)
        lookback_days   : OHLCV 조회 기간
        signal_window   : 최근 N일 이내 시그널 체크
        max_stocks      : 처리 최대 종목 수
        top_n           : 반환 최대 종목 수 (기본 10)
        """
        is_us = market in _US_MARKETS
        has_short = use_short_filter and is_us  # KR은 공매도 데이터 없음
        # KR(공매도 없음): max=65 → threshold=55 / US(공매도 포함): threshold=70
        threshold = SIGNAL_THRESHOLD_US if has_short else SIGNAL_THRESHOLD_KR

        loader = QuantDataLoader()
        snapshot = loader.get_market_snapshot(market=market, max_pages=4)
        if snapshot.empty:
            return pd.DataFrame()

        symbols = snapshot["Symbol"].dropna().tolist()[:max_stocks]
        names = dict(zip(snapshot["Symbol"], snapshot["Name"]))

        # 지수 데이터
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

        results = []

        def _process(symbol: str) -> dict | None:
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
                )

                recent = full_df.tail(signal_window)
                max_score = int(recent["Accum_Score"].max())
                if max_score < threshold:
                    return None

                sig_idx = recent["Accum_Score"].idxmax()
                sig_row = full_df.loc[sig_idx]
                latest = full_df.iloc[-1]

                vol_ma20 = full_df["Volume"].rolling(20).mean().iloc[-1]
                vol_ratio = round(float(latest["Volume"]) / vol_ma20, 2) if vol_ma20 > 0 else 0.0

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
                }
            except Exception:
                return None

        workers = 8 if is_us else 4
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_process, s): s for s in symbols}
            for f in as_completed(futures):
                r = f.result()
                if r:
                    results.append(r)

        if not results:
            return pd.DataFrame()

        return (
            pd.DataFrame(results)
            .sort_values("Score", ascending=False)
            .head(top_n)
            .reset_index(drop=True)
        )
