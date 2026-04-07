"""세력 매집 / 숏커버링 탐지 알고리즘."""

import numpy as np
import pandas as pd

# 시장별 동적 threshold
# - KR(공매도 데이터 없음): 최대 OBV(30)+Alpha(35)=65 → threshold=55
# - US(공매도 포함):        최대 OBV(30)+Alpha(35)+Short(35)=100 → threshold=70
SIGNAL_THRESHOLD_KR = 55
SIGNAL_THRESHOLD_US = 70
SIGNAL_THRESHOLD = SIGNAL_THRESHOLD_US  # 하위 호환용 alias

# 완화 단계별 초기 파라미터 기본값
DEFAULT_OBV_MULTIPLIER = 2.0
DEFAULT_ALPHA_MOMENTUM_THRESHOLD = 0.020


def analyze_whale_with_options(
    df: pd.DataFrame,
    index_df: pd.DataFrame,
    use_alpha: bool = True,
    use_short_filter: bool = False,
    threshold: int = SIGNAL_THRESHOLD_US,
    obv_multiplier: float = DEFAULT_OBV_MULTIPLIER,
    alpha_momentum_threshold: float = DEFAULT_ALPHA_MOMENTUM_THRESHOLD,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    세력 매집 / 숏커버링 시그널 탐지.

    Parameters
    ----------
    df                       : 종목 OHLCV (+ Short_Balance 선택)
    index_df                 : 지수 OHLCV (Close 포함)
    use_alpha                : 지수 대비 상대강도 필터 사용 여부
    use_short_filter         : 공매도 잔고 급감 필터 사용 여부
    threshold                : 신호 기준 점수 (KR=55, US=70)
    obv_multiplier           : OBV 스파이크 판정 거래량 배수 (기본 2.0)
    alpha_momentum_threshold : 강한 모멘텀 알파 임계값, 기본 0.02 (2%)

    Returns
    -------
    (full_df, buy_signals_df)
    """
    df = df.copy()
    df["Accum_Score"] = 0

    # 1. OBV + 매집봉 (가중치 30) — 거래량 obv_multiplier배 이상 + 위꼬리
    df["OBV"] = np.where(
        df["Close"] > df["Close"].shift(1), df["Volume"],
        np.where(df["Close"] < df["Close"].shift(1), -df["Volume"], 0),
    ).cumsum()
    vol_avg = df["Volume"].rolling(window=20).mean()
    df["Is_Whale_Spike"] = (
        (df["Volume"] > vol_avg * obv_multiplier) & (df["High"] > df["Close"])
    )
    df["Accum_Score"] += df["Is_Whale_Spike"].astype(int) * 30

    # 2. 지수 대비 상대강도 (Alpha, 가중치 35)
    #    - 지수 하락일 방어 알파 (고전적 매집 패턴)
    #    - 또는 지수 대비 alpha_momentum_threshold 이상 강세 (모멘텀 알파)
    if use_alpha and not index_df.empty:
        df["Stock_Ret"] = df["Close"].pct_change()
        index_ret = (
            index_df["Close"]
            .pct_change()
            .reindex(df.index, method="ffill")
        )
        df["Alpha"] = df["Stock_Ret"] - index_ret
        df["Alpha_Sig"] = (
            ((index_ret < 0) & (df["Alpha"] > 0))
            | (df["Alpha"] > alpha_momentum_threshold)
        ).astype(int)
        df["Accum_Score"] += df["Alpha_Sig"] * 35

    # 3. 공매도 잔고 급감 (Short Covering, 가중치 35)
    if use_short_filter and "Short_Balance" in df.columns:
        short_avg = df["Short_Balance"].rolling(window=20).mean()
        df["Short_Sig"] = (
            df["Short_Balance"] < short_avg * 0.8
        ).astype(int)
        df["Accum_Score"] += df["Short_Sig"] * 35

    buy_signals = df[df["Accum_Score"] >= threshold].copy()
    return df, buy_signals


def extract_highlights(
    df: pd.DataFrame,
    threshold: int = SIGNAL_THRESHOLD_US,
) -> list[dict]:
    """
    Accum_Score >= threshold 인 날짜를 연속 구간으로 묶어 반환.
    recharts reference_area x1/x2 용.
    """
    signal_dates = df[df["Accum_Score"] >= threshold].index
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
