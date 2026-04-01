"""Backtester 단위 테스트 (네트워크 불필요)."""

import numpy as np
import pandas as pd
import pytest
from backtester import Backtester


@pytest.fixture
def bt():
    return Backtester.__new__(Backtester)  # __init__ 호출 없이 인스턴스 생성


# ---------------------------------------------------------------------------
# MDD 계산 검증
# ---------------------------------------------------------------------------

def test_mdd_simple(bt):
    equity = pd.Series([100.0, 120.0, 80.0, 130.0, 90.0])
    mdd = bt._calc_mdd(equity)
    # 120 → 80 낙폭: (80-120)/120 = -0.3333...
    assert abs(mdd - (-40 / 120)) < 1e-6


def test_mdd_monotone_up(bt):
    """계속 오르면 MDD = 0."""
    equity = pd.Series([100.0, 110.0, 120.0, 130.0])
    assert bt._calc_mdd(equity) == 0.0


def test_mdd_worst_case(bt):
    """처음이 최고점, 마지막이 최저점."""
    equity = pd.Series([200.0, 150.0, 100.0, 50.0])
    mdd = bt._calc_mdd(equity)
    assert abs(mdd - (-150 / 200)) < 1e-6


def test_mdd_recovery(bt):
    """낙폭 후 완전 회복 시 MDD는 낙폭 구간 기준."""
    equity = pd.Series([100.0, 50.0, 100.0, 150.0])
    mdd = bt._calc_mdd(equity)
    assert abs(mdd - (-0.5)) < 1e-6


# ---------------------------------------------------------------------------
# Sharpe 계산 검증
# ---------------------------------------------------------------------------

def test_sharpe_flat(bt):
    """수익률 변동 없으면 Sharpe = 0."""
    equity = pd.Series([100.0] * 100)
    assert bt._calc_sharpe(equity) == 0.0


def test_sharpe_positive_trend(bt):
    """안정적 상승 → Sharpe > 0."""
    equity = pd.Series([100.0 + i * 0.3 for i in range(252)])
    assert bt._calc_sharpe(equity) > 0


def test_sharpe_negative_trend(bt):
    """안정적 하락 → Sharpe < 0."""
    equity = pd.Series([100.0 - i * 0.3 for i in range(252)])
    assert bt._calc_sharpe(equity) < 0


def test_sharpe_high_volatility_low_return(bt):
    """변동성이 크고 수익이 낮으면 Sharpe 작음."""
    np.random.seed(0)
    noisy = 100 + np.cumsum(np.random.randn(252) * 5)  # 고변동
    stable = 100 + np.arange(252) * 0.05               # 저변동
    sharpe_noisy = bt._calc_sharpe(pd.Series(noisy))
    sharpe_stable = bt._calc_sharpe(pd.Series(stable))
    assert sharpe_stable > sharpe_noisy


# ---------------------------------------------------------------------------
# _simulate 검증
# ---------------------------------------------------------------------------

def _make_sim_df(prices, vwap_value=None):
    """시뮬레이션용 DataFrame 생성 헬퍼."""
    n = len(prices)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.array(prices, dtype=float)
    df = pd.DataFrame({
        "Open": close, "High": close * 1.005,
        "Low": close * 0.995, "Close": close,
        "Volume": np.full(n, 500_000.0),
    }, index=idx)
    if vwap_value is not None:
        df["VWAP_20"] = vwap_value
    return df


def test_simulate_one_profitable_trade(bt):
    """매수 후 고점 청산 → 수익 거래 1건."""
    prices = [10_000] * 5 + [12_000] * 5 + [9_000] * 10
    df = _make_sim_df(prices, vwap_value=10_000.0)
    n = len(prices)
    idx = df.index
    buy  = pd.Series([True] + [False] * (n - 1), index=idx)
    sell = pd.Series([False] * 7 + [True] + [False] * (n - 8), index=idx)  # day7=12000

    trades, equity = bt._simulate(df, buy, sell, "VWAP_20", 10_000_000)
    assert len(trades) >= 1
    assert trades[0]["Return"] > 0  # 10000 매수 → 12000 청산 (day7)


def test_simulate_no_signal(bt):
    """매수/매도 신호 없으면 거래 0건, 자본금 불변."""
    prices = [10_000] * 30
    df = _make_sim_df(prices, vwap_value=10_000.0)
    n = len(prices)
    idx = df.index
    buy  = pd.Series([False] * n, index=idx)
    sell = pd.Series([False] * n, index=idx)

    trades, equity = bt._simulate(df, buy, sell, "VWAP_20", 5_000_000)
    assert len(trades) == 0
    assert equity[-1] == 5_000_000.0


def test_simulate_equity_length(bt):
    """equity_curve 길이 = DataFrame 길이."""
    prices = [10_000] * 50
    df = _make_sim_df(prices, vwap_value=10_000.0)
    n = len(prices)
    idx = df.index
    buy  = pd.Series([False] * n, index=idx)
    sell = pd.Series([False] * n, index=idx)
    _, equity = bt._simulate(df, buy, sell, "VWAP_20", 1_000_000)
    assert len(equity) == n


def test_simulate_open_position_closed_at_end(bt):
    """기간 종료까지 포지션 미청산 시 마지막 가격으로 강제 청산."""
    prices = [10_000] * 20 + [15_000] * 10  # 계속 상승, 청산 신호 없음
    df = _make_sim_df(prices, vwap_value=9_000.0)
    n = len(prices)
    idx = df.index
    buy  = pd.Series([True] + [False] * (n - 1), index=idx)
    sell = pd.Series([False] * n, index=idx)

    trades, equity = bt._simulate(df, buy, sell, "VWAP_20", 10_000_000)
    assert len(trades) == 1
    assert trades[0]["Exit_Price"] == 15_000.0
    assert trades[0]["Return"] > 0


def test_simulate_capital_conservation(bt):
    """거래 후 현금 + 포지션 가치 = 초기 자본 ± 손익."""
    prices = [10_000] * 5 + [11_000] * 5 + [9_500] * 10
    df = _make_sim_df(prices, vwap_value=9_800.0)
    n = len(prices)
    idx = df.index
    buy  = pd.Series([True] + [False] * (n - 1), index=idx)
    sell = pd.Series([False] * 10 + [True] + [False] * (n - 11), index=idx)

    trades, equity = bt._simulate(df, buy, sell, "VWAP_20", 10_000_000)
    pnl_sum = sum(t["PnL"] for t in trades)
    assert abs(equity[-1] - (10_000_000 + pnl_sum)) < 1  # 소수점 오차 허용
