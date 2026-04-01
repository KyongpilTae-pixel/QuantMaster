"""공유 pytest fixtures."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def ohlcv_uptrend():
    """200일 완만한 상승 추세 OHLCV."""
    np.random.seed(0)
    n = 200
    close = 10_000 + np.cumsum(np.abs(np.random.randn(n)) * 80)
    high = close * 1.01
    low = close * 0.99
    open_ = close * (1 + np.random.randn(n) * 0.003)
    volume = np.random.randint(200_000, 1_000_000, n).astype(float)
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


@pytest.fixture
def ohlcv_downtrend():
    """200일 하락 추세 OHLCV."""
    np.random.seed(1)
    n = 200
    close = 20_000 - np.cumsum(np.abs(np.random.randn(n)) * 80)
    close = np.maximum(close, 1_000)
    high = close * 1.01
    low = close * 0.99
    open_ = close * (1 + np.random.randn(n) * 0.003)
    volume = np.random.randint(200_000, 1_000_000, n).astype(float)
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


@pytest.fixture
def ohlcv_flat():
    """200일 횡보 OHLCV."""
    n = 200
    close = np.full(n, 10_000.0)
    high = close * 1.005
    low = close * 0.995
    volume = np.full(n, 500_000.0)
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": close, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )
