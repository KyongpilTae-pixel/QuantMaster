"""Filter 4 (매물대 소화 및 전고점 돌파) 단위 테스트."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest

from utils.accumulation_indicators import analyze_whale_with_options, compute_threshold


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int, base_price: float = 10_000.0, base_vol: float = 500_000.0) -> pd.DataFrame:
    """단순 횡보 OHLCV (price/volume 변동 없음)."""
    close  = np.full(n, base_price)
    high   = close * 1.005
    low    = close * 0.995
    volume = np.full(n, base_vol)
    idx    = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": close, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


def _make_breakout_df(n: int = 100) -> pd.DataFrame:
    """
    Squeeze → Breakout 패턴을 인위적으로 생성한 OHLCV.

    구조:
      [0:60]  기준 횡보 (60일 최고가 = 10_050)
      [60:75] Squeeze 구간: 변동폭 축소, 가격 유지
      [75:]   돌파 구간: 가격 10_100 (>10_050) + 거래량 2배
    """
    np.random.seed(42)
    idx = pd.date_range("2023-01-01", periods=n, freq="B")

    close  = np.full(n, 10_000.0)
    high   = np.full(n, 10_050.0)   # 기준 60일 최고가
    low    = np.full(n, 9_950.0)
    volume = np.full(n, 500_000.0)

    # Squeeze 구간 [60:75]: 변동폭을 절반으로 줄임
    high[60:75]   = 10_020.0
    low[60:75]    = 9_980.0

    # 돌파 구간 [75:]: 종가 > 60일 최고가(10_050), 거래량 2배
    close[75:]  = 10_100.0
    high[75:]   = 10_150.0
    low[75:]    = 10_060.0
    volume[75:] = 1_100_000.0  # 500_000 * 1.5 = 750_000 초과

    return pd.DataFrame(
        {"Open": close, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


# ---------------------------------------------------------------------------
# compute_threshold 테스트
# ---------------------------------------------------------------------------

class TestComputeThreshold:
    def test_obv_only(self):
        assert compute_threshold(False, False, use_breakout=False) == 25

    def test_obv_breakout(self):
        assert compute_threshold(False, False, use_breakout=True) == 45

    def test_obv_alpha_no_breakout(self):
        assert compute_threshold(True, False, use_breakout=False) == 55

    def test_obv_short_no_breakout(self):
        assert compute_threshold(False, True, use_breakout=False) == 55

    def test_obv_breakout_alpha(self):
        assert compute_threshold(True, False, use_breakout=True) == 65

    def test_obv_breakout_short(self):
        assert compute_threshold(False, True, use_breakout=True) == 65

    def test_obv_alpha_short_no_breakout(self):
        assert compute_threshold(True, True, use_breakout=False) == 70

    def test_obv_breakout_alpha_short(self):
        assert compute_threshold(True, True, use_breakout=True) == 85

    def test_threshold_increases_with_more_filters(self):
        """필터가 추가될수록 threshold는 단조 증가한다."""
        t0 = compute_threshold(False, False, use_breakout=False)
        t1 = compute_threshold(False, False, use_breakout=True)
        t2 = compute_threshold(True, False, use_breakout=True)
        t3 = compute_threshold(True, True,  use_breakout=True)
        assert t0 <= t1 <= t2 <= t3


# ---------------------------------------------------------------------------
# analyze_whale_with_options — Breakout_Sig 컬럼 생성 확인
# ---------------------------------------------------------------------------

class TestBreakoutColumnCreated:
    def test_breakout_sig_column_exists_when_enabled(self):
        df = _make_ohlcv(120)
        empty_idx = pd.DataFrame()
        result, _ = analyze_whale_with_options(
            df, empty_idx, use_alpha=False, use_short_filter=False,
            use_breakout=True, threshold=1,
        )
        assert "Breakout_Sig" in result.columns

    def test_breakout_sig_column_absent_when_disabled(self):
        df = _make_ohlcv(120)
        empty_idx = pd.DataFrame()
        result, _ = analyze_whale_with_options(
            df, empty_idx, use_alpha=False, use_short_filter=False,
            use_breakout=False, threshold=1,
        )
        assert "Breakout_Sig" not in result.columns

    def test_breakout_sig_zero_when_data_too_short(self):
        """60일 미만 데이터면 Breakout_Sig 컬럼이 생성되지 않는다 (신호 없음과 동일)."""
        df = _make_ohlcv(50)
        empty_idx = pd.DataFrame()
        result, _ = analyze_whale_with_options(
            df, empty_idx, use_alpha=False, use_short_filter=False,
            use_breakout=True, threshold=1,
        )
        # 데이터 부족 시 컬럼 미생성 → _scan_batch에서 False 처리됨
        if "Breakout_Sig" in result.columns:
            assert result["Breakout_Sig"].sum() == 0
        else:
            assert "Breakout_Sig" not in result.columns


# ---------------------------------------------------------------------------
# 돌파 신호 탐지 정확성
# ---------------------------------------------------------------------------

class TestBreakoutSignalDetection:
    def test_breakout_detected_after_squeeze(self):
        """Squeeze → 돌파 패턴에서 Breakout_Sig가 발생해야 한다."""
        df = _make_breakout_df(n=100)
        empty_idx = pd.DataFrame()
        result, _ = analyze_whale_with_options(
            df, empty_idx, use_alpha=False, use_short_filter=False,
            use_breakout=True, threshold=1,
        )
        breakout_days = result[result["Breakout_Sig"] == 1]
        assert len(breakout_days) > 0, "Squeeze 후 돌파 신호가 탐지되어야 한다"

    def test_breakout_signal_in_correct_zone(self):
        """돌파 신호는 반드시 돌파 구간(index >= 75)에만 발생해야 한다."""
        df = _make_breakout_df(n=100)
        empty_idx = pd.DataFrame()
        result, _ = analyze_whale_with_options(
            df, empty_idx, use_alpha=False, use_short_filter=False,
            use_breakout=True, threshold=1,
        )
        breakout_positions = result.index[result["Breakout_Sig"] == 1]
        for pos in breakout_positions:
            assert result.index.get_loc(pos) >= 75, (
                f"돌파 신호가 돌파 구간(75~) 이전에 발생: {pos}"
            )

    def test_no_breakout_on_flat_price(self):
        """변동 없는 횡보에서는 Breakout_Sig = 0이어야 한다."""
        df = _make_ohlcv(120)
        empty_idx = pd.DataFrame()
        result, _ = analyze_whale_with_options(
            df, empty_idx, use_alpha=False, use_short_filter=False,
            use_breakout=True, threshold=1,
        )
        assert result["Breakout_Sig"].sum() == 0

    def test_no_breakout_without_volume_surge(self):
        """가격은 돌파해도 거래량이 수반되지 않으면 신호 없음."""
        df = _make_breakout_df(n=100)
        # 돌파 구간 거래량을 평균 이하로 낮춤
        df.iloc[75:, df.columns.get_loc("Volume")] = 300_000.0
        empty_idx = pd.DataFrame()
        result, _ = analyze_whale_with_options(
            df, empty_idx, use_alpha=False, use_short_filter=False,
            use_breakout=True, threshold=1,
        )
        assert result["Breakout_Sig"].sum() == 0

    def test_no_breakout_without_squeeze(self):
        """Squeeze 선행 없이 돌파만 있으면 신호 없음."""
        df = _make_breakout_df(n=100)
        # Squeeze 구간의 변동폭을 원래대로 복원 (Squeeze 제거)
        df.iloc[60:75, df.columns.get_loc("High")] = 10_050.0
        df.iloc[60:75, df.columns.get_loc("Low")]  = 9_950.0
        empty_idx = pd.DataFrame()
        result, _ = analyze_whale_with_options(
            df, empty_idx, use_alpha=False, use_short_filter=False,
            use_breakout=True, threshold=1,
        )
        assert result["Breakout_Sig"].sum() == 0


# ---------------------------------------------------------------------------
# Accum_Score 가중치 확인
# ---------------------------------------------------------------------------

class TestBreakoutScoreWeight:
    def test_breakout_adds_30_points(self):
        """Breakout_Sig == 1인 날의 Accum_Score 기여분이 30이어야 한다."""
        df = _make_breakout_df(n=100)
        empty_idx = pd.DataFrame()

        # breakout만 활성화 (obv/alpha/short 비활성)
        result_with, _    = analyze_whale_with_options(
            df, empty_idx, use_alpha=False, use_short_filter=False,
            use_breakout=True, threshold=1,
        )
        result_without, _ = analyze_whale_with_options(
            df, empty_idx, use_alpha=False, use_short_filter=False,
            use_breakout=False, threshold=1,
        )

        breakout_mask = result_with["Breakout_Sig"] == 1
        if breakout_mask.any():
            diff = (
                result_with.loc[breakout_mask, "Accum_Score"].values
                - result_without.loc[breakout_mask, "Accum_Score"].values
            )
            assert (diff == 30).all(), f"돌파 신호 가중치가 30이 아님: {diff}"

    def test_combined_score_obv_plus_breakout(self):
        """OBV 스파이크 + 돌파 동시 발생 시 점수 = 60이어야 한다."""
        df = _make_breakout_df(n=100)
        # 돌파 구간에 OBV 스파이크도 추가 (거래량 3배 + 위꼬리)
        df.iloc[76, df.columns.get_loc("Volume")] = 1_600_000.0  # > 500_000*2
        df.iloc[76, df.columns.get_loc("High")]   = 10_200.0
        df.iloc[76, df.columns.get_loc("Close")]  = 10_100.0
        empty_idx = pd.DataFrame()
        result, _ = analyze_whale_with_options(
            df, empty_idx, use_alpha=False, use_short_filter=False,
            use_breakout=True, threshold=1,
        )
        max_score = result["Accum_Score"].max()
        assert max_score >= 60, f"OBV+돌파 최대점수가 60 미만: {max_score}"


# ---------------------------------------------------------------------------
# 다른 필터와의 독립성
# ---------------------------------------------------------------------------

class TestBreakoutIndependence:
    def test_existing_filters_unaffected_by_breakout_flag(self):
        """use_breakout=False 일 때 Is_Whale_Spike·Alpha_Sig 결과가 동일해야 한다."""
        np.random.seed(10)
        n = 150
        close  = 10_000 + np.cumsum(np.random.randn(n) * 50)
        high   = close * 1.01
        low    = close * 0.99
        volume = np.random.randint(200_000, 1_000_000, n).astype(float)
        idx    = pd.date_range("2023-01-01", periods=n, freq="B")
        df = pd.DataFrame(
            {"Open": close, "High": high, "Low": low, "Close": close, "Volume": volume},
            index=idx,
        )
        index_close = close * (1 + np.random.randn(n) * 0.005)
        index_df = pd.DataFrame({"Close": index_close}, index=idx)

        r_on,  _ = analyze_whale_with_options(
            df, index_df, use_alpha=True, use_short_filter=False,
            use_breakout=True, threshold=1,
        )
        r_off, _ = analyze_whale_with_options(
            df, index_df, use_alpha=True, use_short_filter=False,
            use_breakout=False, threshold=1,
        )

        pd.testing.assert_series_equal(
            r_on["Is_Whale_Spike"].reset_index(drop=True),
            r_off["Is_Whale_Spike"].reset_index(drop=True),
            check_names=False,
        )
        pd.testing.assert_series_equal(
            r_on["Alpha_Sig"].reset_index(drop=True),
            r_off["Alpha_Sig"].reset_index(drop=True),
            check_names=False,
        )
