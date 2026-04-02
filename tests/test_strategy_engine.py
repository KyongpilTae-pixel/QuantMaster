"""strategy_engine.calculate_pullback_plan 단위 테스트."""

import math
import pytest
from utils.strategy_engine import calculate_pullback_plan


# ---------------------------------------------------------------------------
# 기본 3분할 (표준 케이스)
# ---------------------------------------------------------------------------

@pytest.fixture
def standard_plan():
    return calculate_pullback_plan(
        current_price=12_000,
        vwap_price=10_000,
        mfi=60,
        total_budget=10_000_000,
    )


def test_standard_plan_type(standard_plan):
    assert "3분할" in standard_plan["plan_type"]


def test_standard_plan_has_three_steps(standard_plan):
    assert len(standard_plan["steps"]) == 3


def test_standard_plan_weights_sum_100(standard_plan):
    total = sum(s["weight_pct"] for s in standard_plan["steps"])
    assert abs(total - 100) < 1e-6


def test_standard_plan_amounts_sum_to_budget(standard_plan):
    total = sum(s["amount"] for s in standard_plan["steps"])
    assert abs(total - 10_000_000) < 1


def test_standard_plan_first_price_is_current(standard_plan):
    assert standard_plan["steps"][0]["price"] == 12_000


def test_standard_plan_last_price_is_vwap(standard_plan):
    assert standard_plan["steps"][-1]["price"] == 10_000


def test_standard_plan_mid_price_between(standard_plan):
    mid = standard_plan["steps"][1]["price"]
    assert 10_000 < mid < 12_000


def test_standard_stop_loss_is_vwap_minus_4pct(standard_plan):
    assert abs(standard_plan["stop_loss"] - 10_000 * 0.96) < 1


def test_standard_avg_price_between_vwap_and_current(standard_plan):
    avg = standard_plan["avg_price"]
    assert 10_000 <= avg <= 12_000


# ---------------------------------------------------------------------------
# 조건 A: MFI 과열 (≥ 80) → 방어적 3분할
# ---------------------------------------------------------------------------

@pytest.fixture
def defensive_plan():
    return calculate_pullback_plan(
        current_price=12_000,
        vwap_price=10_000,
        mfi=85,
        total_budget=10_000_000,
    )


def test_defensive_plan_type(defensive_plan):
    assert "방어" in defensive_plan["plan_type"] or "과열" in defensive_plan["plan_type"]


def test_defensive_first_weight_is_10pct(defensive_plan):
    assert defensive_plan["steps"][0]["weight_pct"] == 10


def test_defensive_last_weight_is_60pct(defensive_plan):
    assert defensive_plan["steps"][-1]["weight_pct"] == 60


def test_defensive_weights_sum_100(defensive_plan):
    total = sum(s["weight_pct"] for s in defensive_plan["steps"])
    assert abs(total - 100) < 1e-6


def test_defensive_avg_price_lower_than_standard():
    """방어적 플랜은 3차 비중이 크므로 표준 플랜보다 평균 단가가 낮아야 함."""
    std = calculate_pullback_plan(12_000, 10_000, 60, 10_000_000)
    dfn = calculate_pullback_plan(12_000, 10_000, 85, 10_000_000)
    assert dfn["avg_price"] < std["avg_price"]


# ---------------------------------------------------------------------------
# 조건 B: 밀착 상태 (gap ≤ 2%) → 2분할
# ---------------------------------------------------------------------------

@pytest.fixture
def two_split_plan():
    # gap = (10_100 - 10_000) / 10_000 * 100 = 1% → 밀착
    return calculate_pullback_plan(
        current_price=10_100,
        vwap_price=10_000,
        mfi=55,
        total_budget=10_000_000,
    )


def test_two_split_plan_type(two_split_plan):
    assert "2분할" in two_split_plan["plan_type"]


def test_two_split_has_two_steps(two_split_plan):
    assert len(two_split_plan["steps"]) == 2


def test_two_split_each_50pct(two_split_plan):
    for s in two_split_plan["steps"]:
        assert s["weight_pct"] == 50


def test_two_split_amounts_sum_to_budget(two_split_plan):
    total = sum(s["amount"] for s in two_split_plan["steps"])
    assert abs(total - 10_000_000) < 1


# ---------------------------------------------------------------------------
# 경계값 및 엣지 케이스
# ---------------------------------------------------------------------------

def test_mfi_exactly_80_triggers_defensive():
    plan = calculate_pullback_plan(12_000, 10_000, 80, 5_000_000)
    assert plan["steps"][0]["weight_pct"] == 10


def test_gap_exactly_2pct_triggers_two_split():
    # gap = 2% → 조건 B
    plan = calculate_pullback_plan(10_200, 10_000, 55, 5_000_000)
    assert len(plan["steps"]) == 2


def test_stop_loss_pct_is_negative():
    plan = calculate_pullback_plan(12_000, 10_000, 60, 1_000_000)
    assert plan["stop_loss_pct"] < 0


def test_shares_positive_for_all_steps():
    plan = calculate_pullback_plan(12_000, 10_000, 60, 10_000_000)
    for s in plan["steps"]:
        assert s["shares"] > 0
