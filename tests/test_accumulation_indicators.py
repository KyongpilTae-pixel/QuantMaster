"""
세력 탐지 알고리즘 단위 테스트.

핵심 버그 검증 및 수정 후 동작 확인.

주요 수정 사항:
  1. KR threshold 55 (기존 70은 max=65여서 불가)
  2. OBV 볼륨 2x (기존 3x, rolling mean 포함 감안 3.0x 테스트 사용)
  3. Alpha: 지수 하락 방어 알파 OR 2%+ 모멘텀 알파
  4. signal_window 15일 (기존 5일)
"""

import numpy as np
import pandas as pd
import pytest


def _make_ohlcv(n: int, volume_multipliers: dict = None) -> pd.DataFrame:
    """n일치 더미 OHLCV. volume_multipliers: {idx: multiplier} 로 특정 일 거래량 배율 설정."""
    idx = pd.bdate_range("2025-01-01", periods=n)
    close = pd.Series(100.0 + np.arange(n) * 0.1, index=idx)
    vol = pd.Series([1_000_000.0] * n, index=idx)
    if volume_multipliers:
        for i, mult in volume_multipliers.items():
            vol.iloc[i] = 1_000_000.0 * mult
    return pd.DataFrame({
        "Open": close - 0.5,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": vol,
    }, index=idx)


def _make_index(df: pd.DataFrame, down_days: set = None) -> pd.DataFrame:
    """종목과 같은 날짜의 지수 더미. down_days: 하락 일 위치 집합(iloc 기준)."""
    close = pd.Series(1000.0, index=df.index)
    if down_days:
        for i in down_days:
            close.iloc[i] = close.iloc[i - 1] * 0.98 if i > 0 else 980.0
    return pd.DataFrame({"Close": close}, index=df.index)


# ---------------------------------------------------------------------------
# 1. 점수 산정 기본 동작
# ---------------------------------------------------------------------------

class TestScoreComputation:
    def test_no_signals_score_zero(self):
        """아무 시그널 없으면 점수 0."""
        from utils.accumulation_indicators import analyze_whale_with_options
        df = _make_ohlcv(60)
        idx = _make_index(df)
        full, _ = analyze_whale_with_options(df, idx, use_alpha=True, use_short_filter=False)
        assert full["Accum_Score"].max() == 0

    def test_obv_spike_adds_30(self):
        """OBV 매집봉(거래량 3.0x) -> Is_Whale_Spike=True, +30점.

        rolling(20) mean이 스파이크 당일 포함:
          vol_avg_last = (19 x 1M + 3M) / 20 = 1.1M
          3M > 1.1M x 2 = 2.2M  ->  Is_Whale_Spike=True
        """
        from utils.accumulation_indicators import analyze_whale_with_options
        df = _make_ohlcv(40, volume_multipliers={-1: 3.0})
        idx = _make_index(df)
        full, _ = analyze_whale_with_options(df, idx, use_alpha=False, use_short_filter=False)
        assert full["Is_Whale_Spike"].iloc[-1] == True
        assert full["Accum_Score"].iloc[-1] == 30

    def test_alpha_adds_35_on_down_day(self):
        """시장 하락일에 종목 양의 알파 -> Alpha_Sig=1, +35점."""
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n)
        # 마지막 날 종목은 +3% 상승, 지수는 -2% 하락
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        idx = _make_index(df, down_days={n - 1})
        full, _ = analyze_whale_with_options(df, idx, use_alpha=True, use_short_filter=False)
        assert full["Alpha_Sig"].iloc[-1] == 1
        assert full["Accum_Score"].iloc[-1] == 35

    def test_alpha_adds_35_strong_momentum(self):
        """지수 상승 시에도 2%+ 강세 알파 -> Alpha_Sig=1."""
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n)
        # 종목 +3%, 지수 +0.5% -> alpha = +2.5% > 2%
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        idx = pd.DataFrame(
            {"Close": [1000.0] * (n - 1) + [1005.0]},
            index=df.index,
        )
        full, _ = analyze_whale_with_options(df, idx, use_alpha=True, use_short_filter=False)
        assert full["Alpha_Sig"].iloc[-1] == 1

    def test_short_covering_adds_35(self):
        """공매도 잔고 급감 -> Short_Sig=1, +35점.

        rolling(20) 포함 감안 충분히 큰 감소 필요.
        최근 5일 400K: avg = (15x1M + 5x400K)/20 = 850K
        400K < 850K x 0.8 = 680K  ->  Short_Sig=1
        """
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n)
        short_bal = pd.Series(1_000_000.0, index=df.index)
        short_bal.iloc[-5:] = 400_000.0
        df["Short_Balance"] = short_bal
        idx = pd.DataFrame()
        full, _ = analyze_whale_with_options(df, idx, use_alpha=False, use_short_filter=True)
        assert full["Short_Sig"].iloc[-1] == 1
        assert full["Accum_Score"].iloc[-1] == 35

    def test_kr_max_score_is_65(self):
        """
        [BUG 검증] KR 시장(공매도 없음): 최대 가능 점수 = OBV(30)+Alpha(35) = 65.
        기존 threshold=70이면 항상 0개 탐지 -> 반드시 동적 threshold 적용 필요.
        """
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n, volume_multipliers={-1: 3.0})
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        idx = _make_index(df, down_days={n - 1})
        full, _ = analyze_whale_with_options(df, idx, use_alpha=True, use_short_filter=False)
        max_score = full["Accum_Score"].max()
        assert max_score == 65, f"KR 최대점수는 65여야 함, 실제={max_score}"
        assert max_score < 70, "threshold=70은 KR에서 수학적으로 불가"

    def test_us_max_score_is_100(self):
        """US 시장: OBV(30)+Alpha(35)+Short(35) = 100 가능."""
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n, volume_multipliers={-1: 3.0})
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        short_bal = pd.Series(1_000_000.0, index=df.index)
        short_bal.iloc[-5:] = 400_000.0
        df["Short_Balance"] = short_bal
        idx = _make_index(df, down_days={n - 1})
        full, _ = analyze_whale_with_options(df, idx, use_alpha=True, use_short_filter=True)
        assert full["Accum_Score"].iloc[-1] == 100


# ---------------------------------------------------------------------------
# 2. 동적 Threshold -- KR=55, US=70
# ---------------------------------------------------------------------------

class TestDynamicThreshold:
    def test_kr_threshold_55_detects_obv_plus_alpha(self):
        """동적 threshold=55 적용 시 KR에서도 OBV(30)+Alpha(35)=65 >= 55 -> 탐지됨."""
        from utils.accumulation_indicators import analyze_whale_with_options, SIGNAL_THRESHOLD_KR
        n = 40
        df = _make_ohlcv(n, volume_multipliers={-1: 3.0})
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        idx = _make_index(df, down_days={n - 1})
        full, _ = analyze_whale_with_options(df, idx, use_alpha=True, use_short_filter=False)
        max_score = full["Accum_Score"].max()
        assert max_score >= SIGNAL_THRESHOLD_KR, (
            f"KR threshold({SIGNAL_THRESHOLD_KR})으로 탐지돼야 함, 점수={max_score}"
        )

    def test_us_threshold_70_unchanged(self):
        """US는 threshold=70 유지."""
        from utils.accumulation_indicators import SIGNAL_THRESHOLD_US
        assert SIGNAL_THRESHOLD_US == 70

    def test_kr_threshold_lower_than_us(self):
        """KR threshold < US threshold."""
        from utils.accumulation_indicators import SIGNAL_THRESHOLD_KR, SIGNAL_THRESHOLD_US
        assert SIGNAL_THRESHOLD_KR < SIGNAL_THRESHOLD_US

    def test_kr_threshold_reachable_from_max_score(self):
        """KR 최대점수(65) >= KR threshold."""
        from utils.accumulation_indicators import SIGNAL_THRESHOLD_KR
        kr_max_score = 30 + 35  # OBV + Alpha (공매도 없음)
        assert kr_max_score >= SIGNAL_THRESHOLD_KR


# ---------------------------------------------------------------------------
# 3. OBV 볼륨 임계값 -- 2x 기준
# ---------------------------------------------------------------------------

class TestOBVThreshold:
    def test_3x_volume_triggers_spike(self):
        """거래량 3.0x -> Is_Whale_Spike=True (2x 기준, rolling mean 자기포함 고려)."""
        from utils.accumulation_indicators import analyze_whale_with_options
        df = _make_ohlcv(40, volume_multipliers={-1: 3.0})
        idx = pd.DataFrame()
        full, _ = analyze_whale_with_options(df, idx, use_alpha=False, use_short_filter=False)
        assert full["Is_Whale_Spike"].iloc[-1] == True

    def test_1x_volume_no_spike(self):
        """거래량이 평균 수준이면 Is_Whale_Spike=False."""
        from utils.accumulation_indicators import analyze_whale_with_options
        df = _make_ohlcv(40)
        idx = pd.DataFrame()
        full, _ = analyze_whale_with_options(df, idx, use_alpha=False, use_short_filter=False)
        assert full["Is_Whale_Spike"].any() == False

    def test_obv_spike_score_30(self):
        """OBV 스파이크 발생 시 점수 30점."""
        from utils.accumulation_indicators import analyze_whale_with_options
        df = _make_ohlcv(40, volume_multipliers={-1: 3.0})
        idx = pd.DataFrame()
        full, _ = analyze_whale_with_options(df, idx, use_alpha=False, use_short_filter=False)
        assert full["Accum_Score"].iloc[-1] == 30


# ---------------------------------------------------------------------------
# 4. extract_highlights -- threshold 파라미터
# ---------------------------------------------------------------------------

class TestExtractHighlights:
    def test_empty_when_no_signals(self):
        """시그널 없으면 빈 리스트."""
        from utils.accumulation_indicators import extract_highlights
        df = pd.DataFrame(
            {"Accum_Score": [0, 10, 20, 0]},
            index=pd.bdate_range("2025-01-01", periods=4),
        )
        assert extract_highlights(df, threshold=55) == []

    def test_single_signal_date(self):
        """시그널 1일 -> x1 == x2."""
        from utils.accumulation_indicators import extract_highlights
        df = pd.DataFrame(
            {"Accum_Score": [0, 65, 0, 0]},
            index=pd.bdate_range("2025-01-01", periods=4),
        )
        hl = extract_highlights(df, threshold=55)
        assert len(hl) == 1
        assert hl[0]["x1"] == hl[0]["x2"]

    def test_consecutive_signals_merged(self):
        """연속 3일 시그널 -> 구간 1개."""
        from utils.accumulation_indicators import extract_highlights
        scores = [0, 65, 65, 65, 0]
        df = pd.DataFrame(
            {"Accum_Score": scores},
            index=pd.bdate_range("2025-01-01", periods=5),
        )
        hl = extract_highlights(df, threshold=55)
        assert len(hl) == 1
        assert hl[0]["x1"] != hl[0]["x2"]

    def test_separated_signals_two_ranges(self):
        """6 영업일 이상 간격 -> 구간 2개."""
        from utils.accumulation_indicators import extract_highlights
        idx = pd.bdate_range("2025-01-01", periods=15)
        scores = [65] + [0] * 10 + [65] * 4
        df = pd.DataFrame({"Accum_Score": scores}, index=idx)
        hl = extract_highlights(df, threshold=55)
        assert len(hl) == 2

    def test_kr_threshold_55_used(self):
        """threshold=55 파라미터로 score=65 구간 감지, threshold=70으로는 미감지."""
        from utils.accumulation_indicators import extract_highlights
        df = pd.DataFrame(
            {"Accum_Score": [0, 65, 65, 0]},
            index=pd.bdate_range("2025-01-01", periods=4),
        )
        hl_55 = extract_highlights(df, threshold=55)
        hl_70 = extract_highlights(df, threshold=70)
        assert len(hl_55) == 1   # KR threshold로 감지
        assert len(hl_70) == 0   # 기존 threshold=70이면 미감지 (버그였음)

    def test_default_threshold_backward_compat(self):
        """threshold 기본값 = SIGNAL_THRESHOLD_US(70) -- 하위호환."""
        from utils.accumulation_indicators import extract_highlights, SIGNAL_THRESHOLD_US
        df = pd.DataFrame(
            {"Accum_Score": [100, 0, 0]},
            index=pd.bdate_range("2025-01-01", periods=3),
        )
        hl = extract_highlights(df)   # 기본값 사용
        assert len(hl) == 1


# ---------------------------------------------------------------------------
# 5. buy_signals 반환 -- threshold 파라미터
# ---------------------------------------------------------------------------

class TestBuySignalsFilter:
    def test_buy_signals_use_threshold(self):
        """analyze_whale_with_options가 threshold 파라미터로 buy_signals 필터링."""
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n, volume_multipliers={-1: 3.0})
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        idx = _make_index(df, down_days={n - 1})

        # threshold=55(KR): score 65 -> buy_signals에 포함
        _, buy_55 = analyze_whale_with_options(
            df, idx, use_alpha=True, use_short_filter=False, threshold=55
        )
        # threshold=70(US기본): score 65 -> buy_signals에 미포함
        _, buy_70 = analyze_whale_with_options(
            df, idx, use_alpha=True, use_short_filter=False, threshold=70
        )
        assert len(buy_55) >= 1
        assert len(buy_70) == 0

    def test_all_signals_buy_count(self):
        """세 신호 모두 발생 시 buy_signals에 해당 날 포함."""
        from utils.accumulation_indicators import analyze_whale_with_options
        n = 40
        df = _make_ohlcv(n, volume_multipliers={-1: 3.0})
        df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.03
        df.loc[df.index[-1], "High"] = df.loc[df.index[-1], "Close"] + 1
        short_bal = pd.Series(1_000_000.0, index=df.index)
        short_bal.iloc[-5:] = 400_000.0
        df["Short_Balance"] = short_bal
        idx = _make_index(df, down_days={n - 1})
        _, buy_sigs = analyze_whale_with_options(
            df, idx, use_alpha=True, use_short_filter=True, threshold=70
        )
        assert len(buy_sigs) >= 1
