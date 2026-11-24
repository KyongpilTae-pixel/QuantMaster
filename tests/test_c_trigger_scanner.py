"""Unit tests for utils/c_trigger_scanner.py (no network required)."""
import pandas as pd
import numpy as np
import pytest

from utils.c_trigger_scanner import (
    _gate,
    _check_macro_calendar,
    _check_rates,
    _check_vix,
    _check_fx,
    _check_taa_gate,
    _check_sector,
    _MACRO_CALENDAR,
    _TAA_ASSETS,
)


# ---- Helpers -------------------------------------------------------------------

def _make_series(values: list[float], base: str = "2024-01-01") -> pd.Series:
    idx = pd.date_range(base, periods=len(values), freq="B")
    return pd.Series(values, index=idx)


def _ascending(n: int, start: float = 100.0, step: float = 0.5) -> list[float]:
    return [start + i * step for i in range(n)]


def _flat(n: int, val: float = 100.0) -> list[float]:
    return [val] * n


# ---- _gate() -------------------------------------------------------------------

class TestGate:
    def test_above_ma200_positive_momentum(self):
        # Price rises steadily above MA200 and 12M momentum is positive
        vals = _ascending(260, start=100.0, step=0.1)
        s = _make_series(vals)
        assert _gate(s, s.index[-1]) is True

    def test_below_ma200(self):
        # Start high, then drop below MA200
        vals = _ascending(200, start=200.0, step=0.1) + [80.0] * 60
        s = _make_series(vals)
        assert _gate(s, s.index[-1]) is False

    def test_insufficient_data(self):
        s = _make_series(_flat(100))
        assert _gate(s, s.index[-1]) is False

    def test_cutoff_limits_data(self):
        vals = _ascending(260, start=100.0, step=0.5)
        s = _make_series(vals)
        # Cutoff at day 50 — not enough data for MA200
        assert _gate(s, s.index[50]) is False


# ---- _check_macro_calendar() ---------------------------------------------------

class TestMacroCalendar:
    def test_known_fomc_date(self):
        result = _check_macro_calendar(pd.Timestamp("2026-03-19"))
        assert result is not None
        assert result["type"] == "macro"
        assert "FOMC" in result["title"]

    def test_known_cpi_date(self):
        result = _check_macro_calendar(pd.Timestamp("2026-11-13"))
        assert result is not None
        assert "CPI" in result["title"]

    def test_known_bok_date(self):
        result = _check_macro_calendar(pd.Timestamp("2026-11-27"))
        assert result is not None
        assert "금통위" in result["title"]

    def test_non_event_date(self):
        result = _check_macro_calendar(pd.Timestamp("2026-11-24"))
        assert result is None

    def test_slug_has_no_spaces(self):
        for date_str in list(_MACRO_CALENDAR.keys())[:3]:
            r = _check_macro_calendar(pd.Timestamp(date_str))
            assert " " not in r["slug"]

    def test_required_keys_present(self):
        r = _check_macro_calendar(pd.Timestamp("2026-06-18"))
        for key in ("type", "slug", "title", "event_date", "tags", "highlight", "sections"):
            assert key in r


# ---- _check_rates() ------------------------------------------------------------

class TestRates:
    def _data(self, prev: float, curr: float) -> dict:
        vals = _flat(10, 4.0) + [prev, curr]
        return {"^TNX": _make_series(vals)}

    def test_large_up_move_fires(self):
        data = self._data(4.5, 4.72)  # +22bp
        r = _check_rates(data, data["^TNX"].index[-1])
        assert r is not None
        assert r["type"] == "rates"

    def test_small_move_no_fire(self):
        data = self._data(4.5, 4.51)  # +1bp
        r = _check_rates(data, data["^TNX"].index[-1])
        assert r is None

    def test_round_level_breach_fires(self):
        data = self._data(4.48, 4.52)  # crosses 4.5 (only +4bp but level breach)
        r = _check_rates(data, data["^TNX"].index[-1])
        assert r is not None
        assert "4.5" in r["title"]

    def test_missing_ticker_returns_none(self):
        r = _check_rates({}, pd.Timestamp("2026-11-24"))
        assert r is None

    def test_down_move_fires(self):
        data = self._data(5.0, 4.75)  # -25bp
        r = _check_rates(data, data["^TNX"].index[-1])
        assert r is not None
        assert "하락" in r["title"] or "하향" in r["title"]


# ---- _check_vix() --------------------------------------------------------------

class TestVix:
    def _data(self, prev: float, curr: float) -> dict:
        return {"^VIX": _make_series(_flat(5, 15.0) + [prev, curr])}

    def test_breach_25_fires(self):
        r = _check_vix(self._data(24.5, 25.5), pd.Timestamp("2026-11-24"))
        assert r is not None and "25" in r["title"]

    def test_no_breach_no_fire(self):
        r = _check_vix(self._data(22.0, 23.5), pd.Timestamp("2026-11-24"))
        assert r is None

    def test_downward_breach_no_fire(self):
        # VIX falling through 25 should NOT fire (only upward)
        r = _check_vix(self._data(26.0, 24.0), pd.Timestamp("2026-11-24"))
        assert r is None


# ---- _check_fx() ---------------------------------------------------------------

class TestFx:
    def _data(self, prev_krw: float, curr_krw: float) -> dict:
        # KRW=X stores USD per 1 KRW (small number)
        prev_raw = 1.0 / prev_krw
        curr_raw = 1.0 / curr_krw
        return {"KRW=X": _make_series(_flat(5, 1.0 / 1380) + [prev_raw, curr_raw])}

    def test_level_breach_fires(self):
        r = _check_fx(self._data(1395.0, 1405.0), pd.Timestamp("2026-11-24"))
        assert r is not None and "1,400" in r["title"]

    def test_large_move_fires(self):
        r = _check_fx(self._data(1360.0, 1385.0), pd.Timestamp("2026-11-24"))  # +1.84%
        assert r is not None

    def test_small_move_no_fire(self):
        r = _check_fx(self._data(1380.0, 1382.0), pd.Timestamp("2026-11-24"))  # +0.14%
        assert r is None


# ---- _check_taa_gate() ---------------------------------------------------------

class TestTaaGate:
    def _build_data(self, ticker: str, prev_above: bool, curr_above: bool) -> dict:
        # MA200 = 100. prev_above: price > 100 on day -1. curr_above: price > 100 on day 0.
        base = _flat(252, 100.0)
        base[-2] = 105.0 if prev_above else 95.0
        base[-1] = 105.0 if curr_above else 95.0
        # Ensure 12M momentum is positive (price at -252 is 90, current > 90)
        vals = _flat(10, 90.0) + base
        return {ticker: _make_series(vals)}

    def test_gate_on_to_off_fires(self):
        data = self._build_data("SPY", prev_above=True, curr_above=False)
        target = data["SPY"].index[-1]
        r = _check_taa_gate(data, target)
        assert r is not None
        assert "spy" in r["slug"]
        assert "ON" in r["highlight"]

    def test_gate_off_to_on_fires(self):
        data = self._build_data("EWY", prev_above=False, curr_above=True)
        target = data["EWY"].index[-1]
        r = _check_taa_gate(data, target)
        assert r is not None

    def test_no_change_no_fire(self):
        data = self._build_data("SPY", prev_above=True, curr_above=True)
        target = data["SPY"].index[-1]
        r = _check_taa_gate(data, target)
        assert r is None

    def test_missing_data_no_fire(self):
        r = _check_taa_gate({}, pd.Timestamp("2026-11-24"))
        assert r is None


# ---- _check_sector() -----------------------------------------------------------

class TestSector:
    def _sector_data(self, top_today: str, top_yesterday: str) -> dict:
        """Build mock sector data where specified tickers are on top."""
        from utils.c_trigger_scanner import _US_SECTORS
        data = {}
        tickers = list(_US_SECTORS.keys())
        for t in tickers:
            name = _US_SECTORS[t]
            # Base: flat 30 days at 100
            vals = _flat(30, 100.0)
            if name == top_today:
                vals[-1] = 110.0   # today this sector is #1
                vals[-2] = 103.0
            elif name == top_yesterday:
                vals[-1] = 103.0   # yesterday this was #1
                vals[-2] = 110.0
            data[t] = _make_series(vals, base="2026-11-01")
        return data

    def test_sector_rotation_fires(self):
        from utils.c_trigger_scanner import _US_SECTORS
        names = list(_US_SECTORS.values())
        data = self._sector_data(top_today=names[0], top_yesterday=names[1])
        target = list(data.values())[0].index[-1]
        r = _check_sector(data, target)
        assert r is not None
        assert r["type"] == "sector"

    def test_no_rotation_no_fire(self):
        from utils.c_trigger_scanner import _US_SECTORS
        names = list(_US_SECTORS.values())
        data = self._sector_data(top_today=names[0], top_yesterday=names[0])
        target = list(data.values())[0].index[-1]
        r = _check_sector(data, target)
        assert r is None
