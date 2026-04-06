"""세력 매집 / 숏커버링 탐지 알고리즘."""

import numpy as np
import pandas as pd

SIGNAL_THRESHOLD = 70  # 매수 신호 기준 점수


def analyze_whale_with_options(
    df: pd.DataFrame,
    index_df: pd.DataFrame,
    use_alpha: bool = True,
    use_short_filter: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    세력 매집 / 숏커버링 시그널 탐지.

    Parameters
    ----------
    df               : 종목 OHLCV (+ Short_Balance 선택)
    index_df         : 지수 OHLCV (Close 포함)
    use_alpha        : 지수 대비 상대강도 필터 사용 여부
    use_short_filter : 공매도 잔고 급감 필터 사용 여부

    Returns
    -------
    (full_df, buy_signals_df)
    """
    df = df.copy()
    df["Accum_Score"] = 0

    # 1. OBV + 매집봉 (가중치 30)
    df["OBV"] = np.where(
        df["Close"] > df["Close"].shift(1), df["Volume"],
        np.where(df["Close"] < df["Close"].shift(1), -df["Volume"], 0),
    ).cumsum()
    vol_avg = df["Volume"].rolling(window=20).mean()
    df["Is_Whale_Spike"] = (
        (df["Volume"] > vol_avg * 3) & (df["High"] > df["Close"])
    )
    df["Accum_Score"] += df["Is_Whale_Spike"].astype(int) * 30

    # 2. 지수 대비 상대강도 (Alpha, 가중치 35)
    if use_alpha and not index_df.empty:
        df["Stock_Ret"] = df["Close"].pct_change()
        index_ret = (
            index_df["Close"]
            .pct_change()
            .reindex(df.index, method="ffill")
        )
        df["Alpha"] = df["Stock_Ret"] - index_ret
        df["Alpha_Sig"] = (
            (index_ret < 0) & (df["Alpha"] > 0)
        ).astype(int)
        df["Accum_Score"] += df["Alpha_Sig"] * 35

    # 3. 공매도 잔고 급감 (Short Covering, 가중치 35)
    if use_short_filter and "Short_Balance" in df.columns:
        short_avg = df["Short_Balance"].rolling(window=20).mean()
        df["Short_Sig"] = (
            df["Short_Balance"] < short_avg * 0.8
        ).astype(int)
        df["Accum_Score"] += df["Short_Sig"] * 35

    buy_signals = df[df["Accum_Score"] >= SIGNAL_THRESHOLD].copy()
    return df, buy_signals


def extract_highlights(df: pd.DataFrame) -> list[dict]:
    """
    Accum_Score >= SIGNAL_THRESHOLD 인 날짜를 연속 구간으로 묶어 반환.
    recharts reference_area x1/x2 용.
    """
    signal_dates = df[df["Accum_Score"] >= SIGNAL_THRESHOLD].index
    if len(signal_dates) == 0:
        return []

    highlights, start, prev = [], signal_dates[0], signal_dates[0]
    for d in signal_dates[1:]:
        if (d - prev).days > 5:
            highlights.append({"x1": str(start.date()), "x2": str(prev.date())})
            start = d
        prev = d
    highlights.append({"x1": str(start.date()), "x2": str(prev.date())})
    return highlights
