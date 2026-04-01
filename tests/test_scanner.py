"""QuantScanner 단위 테스트 (data_loader mock 사용)."""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch
from scanner import QuantScanner, _RELAXATION_STEPS, _STEP_LABELS


# ---------------------------------------------------------------------------
# 완화 단계 구조 검증
# ---------------------------------------------------------------------------

def test_relaxation_step_count():
    assert len(_RELAXATION_STEPS) == 5


def test_relaxation_mfi_non_increasing():
    """MFI 임계값은 완화 단계가 올라갈수록 감소하거나 유지."""
    mfi_vals = [s[3] for s in _RELAXATION_STEPS]
    for i in range(1, len(mfi_vals)):
        assert mfi_vals[i] <= mfi_vals[i - 1], \
            f"Step {i}: MFI 임계값이 증가함 {mfi_vals[i-1]} → {mfi_vals[i]}"


def test_relaxation_gpa_non_increasing():
    """GPA 임계값은 완화 단계가 올라갈수록 감소하거나 유지."""
    gpa_vals = [s[2] for s in _RELAXATION_STEPS]
    for i in range(1, len(gpa_vals)):
        assert gpa_vals[i] <= gpa_vals[i - 1]


def test_relaxation_last_step_no_obv():
    """마지막 단계에서는 OBV 조건이 비필수."""
    assert _RELAXATION_STEPS[-1][4] is False


def test_step_labels_all_defined():
    for step_num, *_ in _RELAXATION_STEPS:
        assert step_num in _STEP_LABELS, f"Step {step_num} 라벨 없음"


# ---------------------------------------------------------------------------
# 스캔 로직 검증 (mock 사용)
# ---------------------------------------------------------------------------

def _make_mock_stocks(n=20):
    """PBR이 낮은 종목 목록 생성."""
    symbols = [f"{i:06d}" for i in range(1, n + 1)]
    names = [f"종목{i}" for i in range(1, n + 1)]
    pbr = np.linspace(0.3, 1.8, n)
    roe = np.linspace(5, 30, n)
    gpa = pd.Series(roe).rank(pct=True).values
    return pd.DataFrame({
        "Symbol": symbols, "Name": names,
        "PBR": pbr, "ROE": roe, "GPA_Score": gpa, "Close": np.full(n, 10_000.0),
    })


def _make_pass_ohlcv(vwap_period=120, n=300):
    """모든 기술적 조건을 통과하는 OHLCV."""
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    close = np.full(n, 12_000.0)
    df = pd.DataFrame({
        "Open": close, "High": close * 1.01,
        "Low": close * 0.99, "Close": close,
        "Volume": np.full(n, 1_000_000.0),
    }, index=idx)
    # 지표 컬럼 수동 삽입 (mfi=60, obv 증가 추세)
    df[f"VWAP_{vwap_period}"] = 10_000.0   # Close > VWAP
    df["MFI"] = 60.0                        # > 50
    obv = np.arange(n, dtype=float)
    df["OBV"] = obv
    df["OBV_Sig"] = obv - 100              # OBV > OBV_Sig
    return df


def test_no_duplicate_symbols():
    """동일 종목이 결과에 중복으로 포함되지 않아야 함."""
    mock_stocks = _make_mock_stocks(30)
    pass_df = _make_pass_ohlcv()

    with patch("scanner.QuantDataLoader") as MockLoader:
        loader_inst = MagicMock()
        MockLoader.return_value = loader_inst
        loader_inst.get_market_snapshot.return_value = mock_stocks
        loader_inst.get_ohlcv.return_value = pass_df

        with patch("scanner.TechnicalIndicators.calculate_all", return_value=pass_df):
            scanner = QuantScanner()
            result = scanner.run_advanced_scan(target_pbr=2.0, vwap_period=120, min_count=5)

    assert result["Symbol"].nunique() == len(result), "중복 종목 발견"


def test_result_count_capped_at_min_count():
    """결과는 min_count를 초과하지 않음."""
    mock_stocks = _make_mock_stocks(50)
    pass_df = _make_pass_ohlcv()

    with patch("scanner.QuantDataLoader") as MockLoader:
        loader_inst = MagicMock()
        MockLoader.return_value = loader_inst
        loader_inst.get_market_snapshot.return_value = mock_stocks
        loader_inst.get_ohlcv.return_value = pass_df

        with patch("scanner.TechnicalIndicators.calculate_all", return_value=pass_df):
            scanner = QuantScanner()
            result = scanner.run_advanced_scan(target_pbr=2.0, vwap_period=120, min_count=5)

    assert len(result) <= 5


def test_empty_snapshot_returns_empty():
    """시장 스냅샷이 비어 있으면 빈 DataFrame 반환."""
    with patch("scanner.QuantDataLoader") as MockLoader:
        loader_inst = MagicMock()
        MockLoader.return_value = loader_inst
        loader_inst.get_market_snapshot.return_value = pd.DataFrame()

        scanner = QuantScanner()
        result = scanner.run_advanced_scan()

    assert result.empty


def test_condition_label_in_results():
    """결과 DataFrame에 Condition 컬럼 존재."""
    mock_stocks = _make_mock_stocks(20)
    pass_df = _make_pass_ohlcv()

    with patch("scanner.QuantDataLoader") as MockLoader:
        loader_inst = MagicMock()
        MockLoader.return_value = loader_inst
        loader_inst.get_market_snapshot.return_value = mock_stocks
        loader_inst.get_ohlcv.return_value = pass_df

        with patch("scanner.TechnicalIndicators.calculate_all", return_value=pass_df):
            scanner = QuantScanner()
            result = scanner.run_advanced_scan(target_pbr=2.0, min_count=3)

    if not result.empty:
        assert "Condition" in result.columns
        assert result["Condition"].isin(_STEP_LABELS.values()).all()


def test_applied_threshold_columns_present():
    """결과에 Applied_* 컬럼이 모두 존재."""
    mock_stocks = _make_mock_stocks(20)
    pass_df = _make_pass_ohlcv()

    with patch("scanner.QuantDataLoader") as MockLoader:
        loader_inst = MagicMock()
        MockLoader.return_value = loader_inst
        loader_inst.get_market_snapshot.return_value = mock_stocks
        loader_inst.get_ohlcv.return_value = pass_df

        with patch("scanner.TechnicalIndicators.calculate_all", return_value=pass_df):
            scanner = QuantScanner()
            result = scanner.run_advanced_scan(target_pbr=2.0, min_count=3)

    if not result.empty:
        for col in ["Applied_PBR", "Applied_GPA", "Applied_MFI", "Applied_OBV"]:
            assert col in result.columns, f"{col} 컬럼 없음"
