"""
data_loader 통합 테스트.
실제 네트워크 호출이 필요하므로 기본적으로 skip.
실행: pytest tests/test_data_loader.py -m integration
"""

import pytest
import pandas as pd

pytestmark = pytest.mark.integration  # 전체 파일에 마크 적용


@pytest.fixture(scope="module")
def loader():
    from utils.data_loader import QuantDataLoader
    return QuantDataLoader()


def test_kr_snapshot_returns_dataframe(loader):
    df = loader.get_market_snapshot("KOSPI", max_pages=1)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty


def test_kr_snapshot_required_columns(loader):
    df = loader.get_market_snapshot("KOSPI", max_pages=1)
    for col in ["Symbol", "Name", "PBR", "ROE", "GPA_Score"]:
        assert col in df.columns, f"{col} 컬럼 없음"


def test_kr_snapshot_pbr_positive(loader):
    df = loader.get_market_snapshot("KOSPI", max_pages=1)
    assert (df["PBR"] > 0).all(), "PBR에 0 이하 값 존재"


def test_kr_snapshot_gpa_score_range(loader):
    df = loader.get_market_snapshot("KOSPI", max_pages=1)
    valid = df["GPA_Score"].dropna()
    assert (valid >= 0).all() and (valid <= 1).all()


def test_kr_ohlcv_returns_dataframe(loader):
    df = loader.get_ohlcv("005930", lookback_days=60)  # 삼성전자
    assert isinstance(df, pd.DataFrame)
    assert not df.empty


def test_kr_ohlcv_required_columns(loader):
    df = loader.get_ohlcv("005930", lookback_days=60)
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        assert col in df.columns


def test_kr_ohlcv_no_zero_volume(loader):
    df = loader.get_ohlcv("005930", lookback_days=60)
    assert (df["Volume"] > 0).all()


def test_us_snapshot_returns_dataframe(loader):
    df = loader.get_market_snapshot("SP500", max_pages=1)
    assert isinstance(df, pd.DataFrame)


def test_us_ohlcv_returns_dataframe(loader):
    df = loader.get_ohlcv("AAPL", lookback_days=60)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
