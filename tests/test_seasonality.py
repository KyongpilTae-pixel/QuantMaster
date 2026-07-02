"""
utils/seasonality.py 단위 테스트
"""
import numpy as np
import pandas as pd
import pytest
from utils.seasonality import calc_monthly_seasonality


def _make_df(n: int = 600, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 10_000 * np.cumprod(1 + rng.normal(0.0003, 0.015, n))
    highs  = closes * (1 + rng.uniform(0.000, 0.015, n))
    lows   = closes * (1 - rng.uniform(0.000, 0.015, n))
    dates  = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": closes, "High": highs, "Low": lows}, index=dates)


class TestReturnShape:
    def test_always_12_rows(self):
        df = _make_df(600)
        rows = calc_monthly_seasonality(df, "pullback", 20, hold_days=10)
        assert len(rows) == 12

    def test_month_nums_1_to_12(self):
        df   = _make_df(600)
        rows = calc_monthly_seasonality(df, "pullback", 20)
        nums = [r["month_num"] for r in rows]
        assert nums == list(range(1, 13))

    def test_month_kr_labels(self):
        df   = _make_df(600)
        rows = calc_monthly_seasonality(df, "pullback", 20)
        for i, r in enumerate(rows, 1):
            assert r["month_kr"] == f"{i}월"


class TestRequiredKeys:
    _KEYS = [
        "month_num", "month_kr", "ev", "ev_str", "win_rate", "win_rate_str",
        "avg_profit", "avg_profit_str", "avg_loss", "avg_loss_str",
        "pl_ratio", "pl_ratio_str", "sample_n", "sample_n_str",
        "has_data", "ev_high", "ev_positive", "win_rate_high",
    ]

    def test_all_keys_present(self):
        df   = _make_df(600)
        rows = calc_monthly_seasonality(df, "breakout_n", 20)
        for row in rows:
            for k in self._KEYS:
                assert k in row, f"key '{k}' missing in month {row.get('month_num')}"


class TestBoolFlags:
    def test_ev_high_only_when_ev_ge_1(self):
        df   = _make_df(800)
        rows = calc_monthly_seasonality(df, "pullback", 20)
        for r in rows:
            if r["ev"] is not None:
                assert r["ev_high"] == (r["ev"] >= 1.0)

    def test_ev_positive_only_when_ev_gt_0(self):
        df   = _make_df(800)
        rows = calc_monthly_seasonality(df, "pullback", 20)
        for r in rows:
            if r["ev"] is not None:
                assert r["ev_positive"] == (r["ev"] > 0)

    def test_win_rate_high_only_when_ge_60(self):
        df   = _make_df(800)
        rows = calc_monthly_seasonality(df, "pullback", 10)
        for r in rows:
            assert r["win_rate_high"] == (r["win_rate"] >= 60.0)

    def test_has_data_false_when_no_samples(self):
        """데이터가 너무 짧으면 모든 월 has_data=False"""
        df   = _make_df(25)   # hold_days=20보다 겨우 큰 데이터
        rows = calc_monthly_seasonality(df, "pullback", 20, hold_days=20)
        assert all(not r["has_data"] for r in rows)


class TestEntryTypes:
    def test_pullback_returns_12(self):
        df   = _make_df(600)
        rows = calc_monthly_seasonality(df, "pullback", 10)
        assert len(rows) == 12

    def test_breakout_n_returns_12(self):
        df   = _make_df(600)
        rows = calc_monthly_seasonality(df, "breakout_n", 20)
        assert len(rows) == 12

    def test_box_breakout_returns_12(self):
        df   = _make_df(600)
        rows = calc_monthly_seasonality(df, "box_breakout", 61)
        assert len(rows) == 12

    def test_unknown_entry_type_returns_12_empty(self):
        df   = _make_df(600)
        rows = calc_monthly_seasonality(df, "unknown_type", 20)
        assert len(rows) == 12
        assert all(not r["has_data"] for r in rows)


class TestHoldDays:
    def test_hold_5_different_from_hold_60(self):
        df = _make_df(600)
        r5  = calc_monthly_seasonality(df, "pullback", 20, hold_days=5)
        r60 = calc_monthly_seasonality(df, "pullback", 20, hold_days=60)
        # 같은 달이라도 보유기간 다르면 수익이 다를 수 있음
        evs5  = [r["ev"] for r in r5  if r["ev"] is not None]
        evs60 = [r["ev"] for r in r60 if r["ev"] is not None]
        # 둘 다 데이터가 있으면 완전히 동일하지는 않아야 함
        if evs5 and evs60:
            assert evs5 != evs60

    def test_short_data_returns_empty(self):
        df   = _make_df(10)
        rows = calc_monthly_seasonality(df, "pullback", 20, hold_days=60)
        assert all(not r["has_data"] for r in rows)


class TestStrFormat:
    def test_ev_str_dash_when_no_data(self):
        df   = _make_df(25)
        rows = calc_monthly_seasonality(df, "pullback", 20, hold_days=20)
        assert all(r["ev_str"] == "-" for r in rows)

    def test_sample_n_str_is_string(self):
        df   = _make_df(600)
        rows = calc_monthly_seasonality(df, "pullback", 20)
        for r in rows:
            assert isinstance(r["sample_n_str"], str)
