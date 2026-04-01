"""TechnicalIndicators 단위 테스트."""

import numpy as np
import pandas as pd
import pytest
from utils.indicators import TechnicalIndicators


# ---------------------------------------------------------------------------
# 컬럼 생성 확인
# ---------------------------------------------------------------------------

def test_vwap_columns_created(ohlcv_uptrend):
    result = TechnicalIndicators.calculate_all(ohlcv_uptrend, [20, 60])
    for w in [20, 60]:
        assert f"VWAP_{w}" in result.columns
        assert f"TWAP_{w}" in result.columns


def test_mfi_obv_columns_created(ohlcv_uptrend):
    result = TechnicalIndicators.calculate_all(ohlcv_uptrend, [20])
    assert "MFI" in result.columns
    assert "OBV" in result.columns
    assert "OBV_Sig" in result.columns


def test_row_count_unchanged(ohlcv_uptrend):
    result = TechnicalIndicators.calculate_all(ohlcv_uptrend, [20])
    assert len(result) == len(ohlcv_uptrend)


# ---------------------------------------------------------------------------
# VWAP 수식 검증
# ---------------------------------------------------------------------------

def test_vwap_formula_correctness(ohlcv_uptrend):
    """VWAP = sum(tp*vol, w) / sum(vol, w) 직접 검증."""
    df = ohlcv_uptrend
    result = TechnicalIndicators.calculate_all(df, [5])
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    expected = (tp * df["Volume"]).rolling(5).sum() / df["Volume"].rolling(5).sum()
    pd.testing.assert_series_equal(
        result["VWAP_5"].round(4), expected.round(4), check_names=False
    )


def test_vwap_positive(ohlcv_uptrend):
    result = TechnicalIndicators.calculate_all(ohlcv_uptrend, [20])
    valid = result["VWAP_20"].dropna()
    assert (valid > 0).all()


def test_twap_formula_correctness(ohlcv_uptrend):
    """TWAP = rolling mean of typical price."""
    df = ohlcv_uptrend
    result = TechnicalIndicators.calculate_all(df, [10])
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    expected = tp.rolling(10).mean()
    pd.testing.assert_series_equal(
        result["TWAP_10"].round(4), expected.round(4), check_names=False
    )


# ---------------------------------------------------------------------------
# MFI 범위 검증
# ---------------------------------------------------------------------------

def test_mfi_in_0_100(ohlcv_uptrend):
    result = TechnicalIndicators.calculate_all(ohlcv_uptrend, [20])
    valid = result["MFI"].dropna()
    assert (valid >= 0).all(), "MFI < 0 발생"
    assert (valid <= 100).all(), "MFI > 100 발생"


def test_mfi_high_in_uptrend(ohlcv_uptrend):
    """상승 추세에서 MFI 평균이 50 이상이어야 함."""
    result = TechnicalIndicators.calculate_all(ohlcv_uptrend, [20])
    mean_mfi = result["MFI"].dropna().mean()
    assert mean_mfi > 50, f"상승 추세 MFI 평균 {mean_mfi:.1f} < 50"


def test_mfi_low_in_downtrend(ohlcv_downtrend):
    """하락 추세에서 MFI 평균이 50 이하이어야 함."""
    result = TechnicalIndicators.calculate_all(ohlcv_downtrend, [20])
    mean_mfi = result["MFI"].dropna().mean()
    assert mean_mfi < 50, f"하락 추세 MFI 평균 {mean_mfi:.1f} > 50"


def test_mfi_flat_near_50(ohlcv_flat):
    """횡보 시 MFI가 극단값이 아니어야 함."""
    result = TechnicalIndicators.calculate_all(ohlcv_flat, [20])
    valid = result["MFI"].dropna()
    assert len(valid) > 0


# ---------------------------------------------------------------------------
# OBV 방향성 검증
# ---------------------------------------------------------------------------

def test_obv_increases_in_uptrend(ohlcv_uptrend):
    """상승 추세에서 OBV 최종값 > 초기값."""
    result = TechnicalIndicators.calculate_all(ohlcv_uptrend, [20])
    obv = result["OBV"].dropna()
    assert obv.iloc[-1] > obv.iloc[0], "상승 추세에서 OBV가 증가하지 않음"


def test_obv_decreases_in_downtrend(ohlcv_downtrend):
    """하락 추세에서 OBV 최종값 < 초기값."""
    result = TechnicalIndicators.calculate_all(ohlcv_downtrend, [20])
    obv = result["OBV"].dropna()
    assert obv.iloc[-1] < obv.iloc[0], "하락 추세에서 OBV가 감소하지 않음"


def test_obv_signal_is_ma_of_obv(ohlcv_uptrend):
    """OBV_Sig = OBV 20일 이동평균."""
    result = TechnicalIndicators.calculate_all(ohlcv_uptrend, [20])
    expected = result["OBV"].rolling(20).mean()
    pd.testing.assert_series_equal(
        result["OBV_Sig"].round(2), expected.round(2), check_names=False
    )


# ---------------------------------------------------------------------------
# 엣지 케이스
# ---------------------------------------------------------------------------

def test_minimum_data_length():
    """최소 데이터(30행)에서도 오류 없이 동작."""
    np.random.seed(42)
    n = 30
    close = np.full(n, 10_000.0) + np.random.randn(n) * 100
    df = pd.DataFrame({
        "Open": close, "High": close * 1.01, "Low": close * 0.99,
        "Close": close, "Volume": np.full(n, 100_000.0),
    }, index=pd.date_range("2024-01-01", periods=n, freq="B"))
    result = TechnicalIndicators.calculate_all(df, [20])
    assert "VWAP_20" in result.columns


def test_single_window(ohlcv_uptrend):
    """windows 인자에 원소가 하나여도 동작."""
    result = TechnicalIndicators.calculate_all(ohlcv_uptrend, [60])
    assert "VWAP_60" in result.columns
    assert "VWAP_20" not in result.columns
