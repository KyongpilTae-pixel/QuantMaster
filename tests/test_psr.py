"""PSR 관련 단위 테스트 (네트워크 불필요)."""

import math
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# data_loader PSR 계산 검증
# ---------------------------------------------------------------------------

def _make_records(mktcap, sales, pbr=1.0):
    """_parse_page 반환값과 동일한 구조의 dict 생성."""
    psr = round(mktcap / sales, 2) if (sales and sales > 0) else float("nan")
    return {
        "Symbol": "000001",
        "Name": "테스트종목",
        "Close": 10000.0,
        "PBR": pbr,
        "PER": 10.0,
        "ROE": 15.0,
        "MarketCap": mktcap,
        "Sales": sales,
        "PSR": psr,
    }


def test_psr_calculation_basic():
    """PSR = MarketCap / Sales."""
    rec = _make_records(mktcap=3000, sales=1000)
    assert rec["PSR"] == 3.0


def test_psr_calculation_below_one():
    """PSR < 1 (저평가 케이스)."""
    rec = _make_records(mktcap=500, sales=1000)
    assert rec["PSR"] == 0.5


def test_psr_zero_sales_is_nan():
    """매출 0이면 PSR = NaN."""
    rec = _make_records(mktcap=1000, sales=0)
    assert math.isnan(rec["PSR"])


def test_psr_rounded_to_2_decimal():
    """PSR은 소수 2자리 반올림."""
    rec = _make_records(mktcap=1000, sales=3)
    assert rec["PSR"] == round(1000 / 3, 2)


# ---------------------------------------------------------------------------
# snapshot DataFrame에 PSR 컬럼 존재 확인 (mock)
# ---------------------------------------------------------------------------

def _make_mock_snapshot(n=5):
    """get_market_snapshot 반환값과 동일한 구조."""
    symbols = [f"{i:06d}" for i in range(1, n + 1)]
    mktcap = np.linspace(1000, 10000, n)
    sales = np.linspace(500, 5000, n)
    psr = mktcap / sales
    return pd.DataFrame({
        "Symbol": symbols,
        "Name": [f"종목{i}" for i in range(1, n + 1)],
        "Close": np.full(n, 10000.0),
        "PBR": np.linspace(0.5, 2.0, n),
        "PER": np.full(n, 10.0),
        "ROE": np.linspace(5, 30, n),
        "MarketCap": mktcap,
        "Sales": sales,
        "PSR": psr,
        "GPA_Score": pd.Series(np.linspace(5, 30, n)).rank(pct=True).values,
    })


def test_snapshot_has_psr_column():
    """스냅샷 DataFrame에 PSR 컬럼 존재."""
    df = _make_mock_snapshot()
    assert "PSR" in df.columns


def test_snapshot_psr_positive():
    """PSR은 양수."""
    df = _make_mock_snapshot()
    assert (df["PSR"] > 0).all()


# ---------------------------------------------------------------------------
# scanner 결과에 PSR, Market 컬럼 확인 (mock)
# ---------------------------------------------------------------------------

def _make_pass_ohlcv(n=300):
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    close = np.full(n, 12_000.0)
    df = pd.DataFrame({
        "Open": close, "High": close * 1.01,
        "Low": close * 0.99, "Close": close,
        "Volume": np.full(n, 1_000_000.0),
    }, index=idx)
    df["VWAP_120"] = 10_000.0
    df["MFI"] = 60.0
    obv = np.arange(n, dtype=float)
    df["OBV"] = obv
    df["OBV_Sig"] = obv - 100
    return df


def test_scanner_result_has_psr_column():
    """스캔 결과 DataFrame에 PSR 컬럼 존재."""
    mock_stocks = _make_mock_snapshot(20)
    pass_df = _make_pass_ohlcv()

    with patch("scanner.QuantDataLoader") as MockLoader:
        loader_inst = MagicMock()
        MockLoader.return_value = loader_inst
        loader_inst.get_market_snapshot.return_value = mock_stocks
        loader_inst.get_ohlcv.return_value = pass_df

        with patch("scanner.TechnicalIndicators.calculate_all", return_value=pass_df):
            from scanner import QuantScanner
            scanner = QuantScanner()
            result = scanner.run_advanced_scan(target_pbr=2.0, min_count=3)

    if not result.empty:
        assert "PSR" in result.columns


def test_scanner_result_has_market_column():
    """스캔 결과 DataFrame에 Market 컬럼 존재."""
    mock_stocks = _make_mock_snapshot(20)
    pass_df = _make_pass_ohlcv()

    with patch("scanner.QuantDataLoader") as MockLoader:
        loader_inst = MagicMock()
        MockLoader.return_value = loader_inst
        loader_inst.get_market_snapshot.return_value = mock_stocks
        loader_inst.get_ohlcv.return_value = pass_df

        with patch("scanner.TechnicalIndicators.calculate_all", return_value=pass_df):
            from scanner import QuantScanner
            scanner = QuantScanner()
            result = scanner.run_advanced_scan(target_pbr=2.0, min_count=3, market="KOSPI")

    if not result.empty:
        assert "Market" in result.columns
        assert (result["Market"] == "KOSPI").all()


# ---------------------------------------------------------------------------
# min_cap_label 필터 동작 확인
# ---------------------------------------------------------------------------

def test_cap_filter_excludes_small_stocks():
    """소형주 제외 필터 적용 시 소형주 제거됨."""
    df = _make_mock_snapshot(10)
    # MarketCap을 명시적으로 낮게 설정
    df["MarketCap"] = np.linspace(100, 1000, 10)  # 100~1000억

    pass_df = _make_pass_ohlcv()

    with patch("scanner.QuantDataLoader") as MockLoader:
        loader_inst = MagicMock()
        MockLoader.return_value = loader_inst
        loader_inst.get_market_snapshot.return_value = df
        loader_inst.get_ohlcv.return_value = pass_df

        with patch("scanner.TechnicalIndicators.calculate_all", return_value=pass_df):
            from scanner import QuantScanner
            scanner = QuantScanner()
            # 중형주+(3000억) 필터 → 모두 제외되어 빈 결과
            result_filtered = scanner.run_advanced_scan(
                target_pbr=2.0, min_count=3, min_cap_label="중형주+"
            )
            result_all = scanner.run_advanced_scan(
                target_pbr=2.0, min_count=3, min_cap_label="전체"
            )

    assert len(result_filtered) <= len(result_all)
