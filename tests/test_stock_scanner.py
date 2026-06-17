"""
기간별 종목 모멘텀 스캐너 단위 테스트.
실제 네트워크 없이 _calc_stock / fetch_kr_stock_listing 을 monkeypatch해 검증.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd


# ── 헬퍼 ────────────────────────────────────────────────────────────────────

def _make_listing(codes, names, caps_eok):
    return pd.DataFrame({
        "Code":   codes,
        "Name":   names,
        "Marcap": [c * 1e8 for c in caps_eok],
    })


def _raw_result(code="005930", name="삼성전자", ret=15.0, vol=1.5, cap=300_000.0, period="1M"):
    ret_1w = 3.0 if period in ("1M", "3M") else None
    return {
        "code": code, "name": name, "close": 85_000.0,
        "ret_pct": ret, "ret_1w": ret_1w,
        "vol_ratio": vol, "mktcap_eok": cap,
    }


# ── 상수·구조 ────────────────────────────────────────────────────────────────

class TestConstants:

    def test_calendar_days_keys(self):
        from utils.stock_scanner import _CALENDAR_DAYS
        assert set(_CALENDAR_DAYS.keys()) == {"1W", "1M", "3M"}

    def test_trade_days_values(self):
        from utils.stock_scanner import _TRADE_DAYS
        assert _TRADE_DAYS["1W"] == 5
        assert _TRADE_DAYS["1M"] == 20
        assert _TRADE_DAYS["3M"] == 60

    def test_period_labels(self):
        from utils.stock_scanner import PERIOD_LABELS
        assert PERIOD_LABELS["1W"] == "1주"
        assert PERIOD_LABELS["1M"] == "1개월"
        assert PERIOD_LABELS["3M"] == "3개월"


# ── scan_stock_momentum 반환 형식 ─────────────────────────────────────────────

class TestScanStockMomentum:

    @pytest.fixture()
    def mock_listing(self, monkeypatch):
        listing = _make_listing(
            ["005930", "000660", "009150"],
            ["삼성전자", "SK하이닉스", "삼성전기"],
            [3_000_000, 800_000, 80_000],
        )
        import utils.data_loader as dl
        monkeypatch.setattr(dl, "fetch_kr_stock_listing", lambda mkt, mc=0: listing)

    @pytest.fixture()
    def mock_calc(self, monkeypatch):
        import utils.stock_scanner as ss
        ret_map = {"005930": 20.0, "000660": 15.0, "009150": 12.0}

        def fake(args):
            code, name, cap, period = args
            if code not in ret_map:
                return None
            ret_1w = 3.0 if period in ("1M", "3M") else None
            return {
                "code": code, "name": name, "close": 100.0,
                "ret_pct": ret_map[code], "ret_1w": ret_1w,
                "vol_ratio": 1.5, "mktcap_eok": cap,
            }

        monkeypatch.setattr(ss, "_calc_stock", fake)

    def test_returns_list(self, mock_listing, mock_calc):
        from utils.stock_scanner import scan_stock_momentum
        assert isinstance(scan_stock_momentum("KOSPI"), list)

    def test_kr_count(self, mock_listing, mock_calc):
        from utils.stock_scanner import scan_stock_momentum
        assert len(scan_stock_momentum("KOSPI", "1M", 0, 30)) == 3

    def test_sorted_descending(self, mock_listing, mock_calc):
        from utils.stock_scanner import scan_stock_momentum
        result = scan_stock_momentum("KOSPI", "1M", 0, 30)
        rets = [r["ret_pct"] for r in result]
        assert rets == sorted(rets, reverse=True)

    def test_rank_sequential(self, mock_listing, mock_calc):
        from utils.stock_scanner import scan_stock_momentum
        result = scan_stock_momentum("KOSPI", "1M", 0, 30)
        for i, r in enumerate(result):
            assert r["rank"] == i + 1

    def test_top_n_limit(self, mock_listing, mock_calc):
        from utils.stock_scanner import scan_stock_momentum
        result = scan_stock_momentum("KOSPI", "1M", 0, 1)
        assert len(result) == 1

    def test_required_fields(self, mock_listing, mock_calc):
        from utils.stock_scanner import scan_stock_momentum
        required = {
            "rank", "code", "name", "close", "ret_pct",
            "ret_str", "ret_positive",
            "vol_ratio", "vol_ratio_str", "vol_up",
            "close_str", "mktcap_str",
            "ret_1w_str", "ret_1w_positive", "has_ret_1w",
            "is_us",
        }
        result = scan_stock_momentum("KOSPI", "1M", 0, 30)
        for r in result:
            missing = required - r.keys()
            assert not missing, f"필드 누락: {missing}"

    def test_ret_positive_flag(self, mock_listing, mock_calc):
        from utils.stock_scanner import scan_stock_momentum
        result = scan_stock_momentum("KOSPI", "1M", 0, 30)
        for r in result:
            assert r["ret_positive"] == (r["ret_pct"] > 0)

    def test_vol_up_threshold(self, mock_listing, mock_calc):
        from utils.stock_scanner import scan_stock_momentum
        result = scan_stock_momentum("KOSPI", "1M", 0, 30)
        for r in result:
            assert r["vol_up"] == (r["vol_ratio"] >= 1.2)

    def test_ret_1w_available_1m(self, mock_listing, mock_calc):
        from utils.stock_scanner import scan_stock_momentum
        result = scan_stock_momentum("KOSPI", "1M", 0, 30)
        for r in result:
            assert r["has_ret_1w"] is True
            assert r["ret_1w_str"] != "-"

    def test_ret_1w_available_3m(self, mock_listing, mock_calc):
        from utils.stock_scanner import scan_stock_momentum
        result = scan_stock_momentum("KOSPI", "3M", 0, 30)
        for r in result:
            assert r["has_ret_1w"] is True

    def test_ret_1w_absent_for_1w_period(self, mock_listing, mock_calc):
        from utils.stock_scanner import scan_stock_momentum
        result = scan_stock_momentum("KOSPI", "1W", 0, 30)
        for r in result:
            assert r["has_ret_1w"] is False
            assert r["ret_1w_str"] == "-"

    def test_is_us_false_kr(self, mock_listing, mock_calc):
        from utils.stock_scanner import scan_stock_momentum
        result = scan_stock_momentum("KOSPI", "1M", 0, 30)
        for r in result:
            assert r["is_us"] is False

    def test_unknown_period_defaults_1m(self, mock_listing, mock_calc):
        from utils.stock_scanner import scan_stock_momentum
        result = scan_stock_momentum("KOSPI", "INVALID", 0, 30)
        assert isinstance(result, list)

    def test_mktcap_str_jo(self, mock_listing, mock_calc):
        from utils.stock_scanner import scan_stock_momentum
        result = scan_stock_momentum("KOSPI", "1M", 0, 30)
        top = next(r for r in result if r["code"] == "005930")
        assert "조" in top["mktcap_str"]

    def test_none_results_filtered(self, monkeypatch):
        import utils.stock_scanner as ss
        import utils.data_loader as dl
        listing = _make_listing(["005930", "000660"], ["삼성", "SK"], [100_000, 50_000])
        monkeypatch.setattr(dl, "fetch_kr_stock_listing", lambda m, mc=0: listing)

        def mixed(args):
            code, *_ = args
            if code == "005930":
                return {"code": code, "name": "삼성", "close": 100.0,
                        "ret_pct": 10.0, "ret_1w": 2.0, "vol_ratio": 1.3, "mktcap_eok": 100_000}
            return None

        monkeypatch.setattr(ss, "_calc_stock", mixed)
        from utils.stock_scanner import scan_stock_momentum
        result = scan_stock_momentum("KOSPI", "1M", 0, 30)
        assert len(result) == 1
        assert result[0]["code"] == "005930"

    def test_empty_listing_returns_empty(self, monkeypatch):
        import utils.data_loader as dl
        monkeypatch.setattr(dl, "fetch_kr_stock_listing", lambda m, mc=0: pd.DataFrame())
        from utils.stock_scanner import scan_stock_momentum
        assert scan_stock_momentum("KOSPI", "1M", 0, 30) == []


# ── _calc_stock 예외 처리 ─────────────────────────────────────────────────────

class TestCalcStock:

    def test_returns_none_on_exception(self, monkeypatch):
        import utils.stock_scanner as ss

        def fail(*args, **kwargs):
            raise Exception("network error")

        monkeypatch.setattr(ss.fdr, "DataReader", fail)
        result = ss._calc_stock(("005930", "삼성전자", 100_000, "1M"))
        assert result is None

    def test_invalid_period_uses_fallback(self, monkeypatch):
        """_calc_stock은 잘못된 period면 fallback dict 값으로 처리하고 None 반환 가능."""
        import utils.stock_scanner as ss
        import pandas as pd
        from datetime import datetime, timedelta

        # 데이터가 짧아 조기 None 반환되도록
        short_df = pd.DataFrame(
            {"Close": [100.0] * 3, "Volume": [1000] * 3},
            index=pd.date_range("2025-01-01", periods=3),
        )
        monkeypatch.setattr(ss.fdr, "DataReader", lambda *a, **k: short_df)
        result = ss._calc_stock(("005930", "삼성전자", 100_000, "1M"))
        # 데이터 부족 → None
        assert result is None


# ── is_us 플래그 ─────────────────────────────────────────────────────────────

class TestIsUsFlag:

    def test_sp500_returns_is_us_true(self, monkeypatch):
        import utils.stock_scanner as ss
        import FinanceDataReader as fdr_lib

        sp = pd.DataFrame({
            "Symbol": ["AAPL", "MSFT"],
            "Name":   ["Apple", "Microsoft"],
        })
        monkeypatch.setattr(ss.fdr, "StockListing", lambda _: sp)

        called = []

        def fake(args):
            code, name, cap, period = args
            called.append(code)
            ret_1w = 3.0 if period in ("1M", "3M") else None
            return {
                "code": code, "name": name, "close": 200.0,
                "ret_pct": 10.0, "ret_1w": ret_1w,
                "vol_ratio": 1.0, "mktcap_eok": 0,
            }

        monkeypatch.setattr(ss, "_calc_stock", fake)
        from utils.stock_scanner import scan_stock_momentum
        result = scan_stock_momentum("SP500", "1M", 0, 10)
        for r in result:
            assert r["is_us"] is True
