"""tests/test_dividend_scanner.py — 배당 성장 스크리닝 단위+통합 테스트."""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
import pytest

# ---------------------------------------------------------------------------
# 공통 fixture
# ---------------------------------------------------------------------------


def _make_kr_snapshot():
    """NAVER 스냅샷 형태의 KR DataFrame."""
    return pd.DataFrame(
        {
            "Name":      ["삼성전자", "POSCO홀딩스", "기아",  "현대차"],
            "Symbol":    ["005930",   "005490",      "000270","005380"],
            "Close":     [75_000.0,   450_000.0,     85_000.0, 190_000.0],
            "DivYield":  [2.0,        5.5,            3.2,      4.1],
            "MarketCap": [4_000_000,  200_000,        170_000,  400_000],
            "PER":       [12.0,       8.5,            6.0,      7.0],
        }
    )


def _make_yf_ticker(div_yield=0.04, payout=0.5, name="Test Corp",
                    mktcap=5_000_000_000, price=100.0,
                    div_growing=True):
    """yfinance Ticker 목(mock) 객체."""
    t = MagicMock()
    t.info = {
        "dividendYield":      div_yield,
        "payoutRatio":        payout,
        "longName":           name,
        "marketCap":          mktcap,
        "currentPrice":       price,
    }
    # 배당 이력: 성장 여부에 따라 2년치 데이터 구성
    if div_growing:
        # 최근 연도 배당 > 전년도 배당
        idx = pd.date_range("2022-01-01", periods=8, freq="QE")
        vals = [0.4, 0.4, 0.4, 0.4, 0.5, 0.5, 0.5, 0.5]
    else:
        # 배당 감소
        idx = pd.date_range("2022-01-01", periods=8, freq="QE")
        vals = [0.5, 0.5, 0.5, 0.5, 0.4, 0.4, 0.4, 0.4]
    t.dividends = pd.Series(vals, index=idx)
    return t


# ---------------------------------------------------------------------------
# _us_dividend_info 단위 테스트
# ---------------------------------------------------------------------------


class TestUsDividendInfo:
    def test_returns_dict_with_expected_keys(self):
        from utils.dividend_scanner import _us_dividend_info
        mock_t = _make_yf_ticker()
        with patch("utils.dividend_scanner.yf.Ticker", return_value=mock_t):
            result = _us_dividend_info("AAPL")
        assert result is not None
        for key in ("name", "symbol", "market", "price", "div_yield", "payout_ratio",
                    "div_growing", "mktcap_b", "is_us"):
            assert key in result, f"키 누락: {key}"

    def test_div_yield_converted_to_pct(self):
        from utils.dividend_scanner import _us_dividend_info
        mock_t = _make_yf_ticker(div_yield=0.04)
        with patch("utils.dividend_scanner.yf.Ticker", return_value=mock_t):
            result = _us_dividend_info("AAPL")
        assert result is not None
        assert abs(result["div_yield"] - 4.0) < 0.01

    def test_returns_none_when_no_dividend(self):
        from utils.dividend_scanner import _us_dividend_info
        mock_t = _make_yf_ticker(div_yield=0.0)
        with patch("utils.dividend_scanner.yf.Ticker", return_value=mock_t):
            result = _us_dividend_info("NONDIV")
        assert result is None

    def test_div_growing_true(self):
        from utils.dividend_scanner import _us_dividend_info
        mock_t = _make_yf_ticker(div_growing=True)
        with patch("utils.dividend_scanner.yf.Ticker", return_value=mock_t):
            result = _us_dividend_info("AAPL")
        assert result is not None
        assert result["div_growing"] is True

    def test_div_growing_false(self):
        from utils.dividend_scanner import _us_dividend_info
        mock_t = _make_yf_ticker(div_growing=False)
        with patch("utils.dividend_scanner.yf.Ticker", return_value=mock_t):
            result = _us_dividend_info("AAPL")
        assert result is not None
        assert result["div_growing"] is False

    def test_exception_returns_none(self):
        from utils.dividend_scanner import _us_dividend_info
        with patch("utils.dividend_scanner.yf.Ticker", side_effect=Exception("network error")):
            result = _us_dividend_info("ERR")
        assert result is None

    def test_mktcap_in_billions(self):
        from utils.dividend_scanner import _us_dividend_info
        mock_t = _make_yf_ticker(mktcap=2_500_000_000)
        with patch("utils.dividend_scanner.yf.Ticker", return_value=mock_t):
            result = _us_dividend_info("AAPL")
        assert result is not None
        assert abs(result["mktcap_b"] - 2.5) < 0.01


# ---------------------------------------------------------------------------
# _scan_kr_dividend 단위 테스트
# ---------------------------------------------------------------------------


class TestScanKrDividend:
    def test_filters_by_min_yield(self):
        from utils.dividend_scanner import _scan_kr_dividend
        with patch("utils.data_loader.QuantDataLoader") as MockLoader:
            MockLoader.return_value.get_market_snapshot.return_value = _make_kr_snapshot()
            results = _scan_kr_dividend("KOSPI", min_yield_pct=3.0,
                                        max_payout_pct=70.0, top_n=30)
        # DivYield >= 3.0 인 종목: POSCO(5.5), 현대차(4.1), 기아(3.2)
        symbols = [r["symbol"] for r in results]
        assert "005490" in symbols
        assert "005380" in symbols
        assert "000270" in symbols
        assert "005930" not in symbols  # 2.0 < 3.0

    def test_sorted_by_div_yield_desc(self):
        from utils.dividend_scanner import _scan_kr_dividend
        with patch("utils.data_loader.QuantDataLoader") as MockLoader:
            MockLoader.return_value.get_market_snapshot.return_value = _make_kr_snapshot()
            results = _scan_kr_dividend("KOSPI", min_yield_pct=0.0,
                                        max_payout_pct=70.0, top_n=30)
        yields = [r["div_yield"] for r in results]
        assert yields == sorted(yields, reverse=True)

    def test_payout_calc_approximate(self):
        """간이 배당성향: div_yield% × PER / 100."""
        from utils.dividend_scanner import _scan_kr_dividend
        with patch("utils.data_loader.QuantDataLoader") as MockLoader:
            MockLoader.return_value.get_market_snapshot.return_value = _make_kr_snapshot()
            results = _scan_kr_dividend("KOSPI", min_yield_pct=5.0,
                                        max_payout_pct=70.0, top_n=30)
        # POSCO: 5.5 * 8.5 / 100 ≈ 0.468 → 46.8
        posco = next(r for r in results if r["symbol"] == "005490")
        assert posco["payout_ratio"] is not None
        assert abs(posco["payout_ratio"] - 46.75) < 1.0

    def test_top_n_limit(self):
        from utils.dividend_scanner import _scan_kr_dividend
        with patch("utils.data_loader.QuantDataLoader") as MockLoader:
            MockLoader.return_value.get_market_snapshot.return_value = _make_kr_snapshot()
            results = _scan_kr_dividend("KOSPI", min_yield_pct=0.0,
                                        max_payout_pct=70.0, top_n=2)
        assert len(results) <= 2

    def test_missing_columns_returns_empty(self):
        from utils.dividend_scanner import _scan_kr_dividend
        bad_df = pd.DataFrame({"Name": ["A"], "Symbol": ["000001"]})
        with patch("utils.data_loader.QuantDataLoader") as MockLoader:
            MockLoader.return_value.get_market_snapshot.return_value = bad_df
            results = _scan_kr_dividend("KOSPI", 3.0, 70.0, 30)
        assert results == []

    def test_exception_returns_empty(self):
        from utils.dividend_scanner import _scan_kr_dividend
        with patch("utils.data_loader.QuantDataLoader") as MockLoader:
            MockLoader.return_value.get_market_snapshot.side_effect = Exception("오류")
            results = _scan_kr_dividend("KOSPI", 3.0, 70.0, 30)
        assert results == []


# ---------------------------------------------------------------------------
# _scan_us_dividend 단위 테스트
# ---------------------------------------------------------------------------


class TestScanUsDividend:
    def _make_fdr_listing(self):
        return pd.DataFrame({"Symbol": ["AAPL", "MSFT", "JNJ", "XOM"]})

    def test_filters_by_yield_and_payout(self):
        from utils.dividend_scanner import _scan_us_dividend

        def fake_us_info(sym):
            data = {
                "AAPL": {"div_yield": 5.0, "payout_ratio": 40.0, "name": "Apple", "symbol": sym, "market": "SP500",
                          "price": 180.0, "mktcap_b": 3000.0, "div_growing": True, "is_us": True},
                "MSFT": {"div_yield": 1.0, "payout_ratio": 25.0, "name": "Microsoft", "symbol": sym, "market": "SP500",
                          "price": 400.0, "mktcap_b": 3000.0, "div_growing": True, "is_us": True},
                "JNJ":  {"div_yield": 4.0, "payout_ratio": 80.0, "name": "JNJ", "symbol": sym, "market": "SP500",
                          "price": 160.0, "mktcap_b": 400.0, "div_growing": False, "is_us": True},
                "XOM":  {"div_yield": 3.5, "payout_ratio": 50.0, "name": "Exxon", "symbol": sym, "market": "SP500",
                          "price": 120.0, "mktcap_b": 500.0, "div_growing": True, "is_us": True},
            }
            return data.get(sym)

        with patch("utils.dividend_scanner.fdr.StockListing",
                   return_value=self._make_fdr_listing()), \
             patch("utils.dividend_scanner._us_dividend_info", side_effect=fake_us_info):
            results = _scan_us_dividend("SP500", min_yield_pct=3.0,
                                         max_payout_pct=70.0, top_n=30)

        symbols = [r["symbol"] for r in results]
        assert "AAPL" in symbols  # yield 5.0 >= 3.0, payout 40 <= 70
        assert "XOM"  in symbols  # yield 3.5 >= 3.0, payout 50 <= 70
        assert "MSFT" not in symbols  # yield 1.0 < 3.0
        assert "JNJ"  not in symbols  # payout 80 > 70

    def test_sorted_desc_by_yield(self):
        from utils.dividend_scanner import _scan_us_dividend

        def fake_info(sym):
            yields = {"AAPL": 5.0, "MSFT": 4.0, "JNJ": 3.5}
            y = yields.get(sym, 0.0)
            if y < 0.01:
                return None
            return {"div_yield": y, "payout_ratio": 40.0, "name": sym, "symbol": sym,
                    "market": "SP500", "price": 100.0, "mktcap_b": 100.0, "div_growing": True, "is_us": True}

        listing_df = pd.DataFrame({"Symbol": ["AAPL", "MSFT", "JNJ"]})
        with patch("utils.dividend_scanner.fdr.StockListing", return_value=listing_df), \
             patch("utils.dividend_scanner._us_dividend_info", side_effect=fake_info):
            results = _scan_us_dividend("SP500", 0.0, 70.0, 30)

        ys = [r["div_yield"] for r in results]
        assert ys == sorted(ys, reverse=True)

    def test_fdr_exception_returns_empty(self):
        from utils.dividend_scanner import _scan_us_dividend
        with patch("utils.dividend_scanner.fdr.StockListing",
                   side_effect=Exception("network")):
            results = _scan_us_dividend("SP500", 3.0, 70.0, 30)
        assert results == []


# ---------------------------------------------------------------------------
# scan_dividend_stocks 라우팅 단위 테스트
# ---------------------------------------------------------------------------


class TestScanDividendStocks:
    def test_routes_kr(self):
        from utils.dividend_scanner import scan_dividend_stocks
        with patch("utils.dividend_scanner._scan_kr_dividend", return_value=[{"a": 1}]) as mock_kr, \
             patch("utils.dividend_scanner._scan_us_dividend", return_value=[]) as mock_us:
            results = scan_dividend_stocks("KOSPI", 3.0, 70.0, 30)
        mock_kr.assert_called_once()
        mock_us.assert_not_called()
        assert results == [{"a": 1}]

    def test_routes_us(self):
        from utils.dividend_scanner import scan_dividend_stocks
        with patch("utils.dividend_scanner._scan_kr_dividend", return_value=[]) as mock_kr, \
             patch("utils.dividend_scanner._scan_us_dividend", return_value=[{"b": 2}]) as mock_us:
            results = scan_dividend_stocks("SP500", 3.0, 70.0, 30)
        mock_kr.assert_not_called()
        mock_us.assert_called_once()
        assert results == [{"b": 2}]

    def test_unknown_market_returns_empty(self):
        from utils.dividend_scanner import scan_dividend_stocks
        results = scan_dividend_stocks("UNKNOWN", 3.0, 70.0, 30)
        assert results == []


# ---------------------------------------------------------------------------
# 통합 테스트 (실제 네트워크 필요)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDividendScannerIntegration:
    def test_kr_dividend_scan_returns_list(self):
        from utils.dividend_scanner import scan_dividend_stocks
        results = scan_dividend_stocks("KOSPI", min_yield_pct=3.0, top_n=10)
        assert isinstance(results, list)
        if results:
            r = results[0]
            assert "name" in r and "div_yield" in r
            assert r["div_yield"] >= 3.0

    def test_us_dividend_scan_returns_list(self):
        from utils.dividend_scanner import scan_dividend_stocks
        results = scan_dividend_stocks("SP500", min_yield_pct=2.0, top_n=5)
        assert isinstance(results, list)
        for r in results:
            assert r["is_us"] is True
            assert r["div_yield"] >= 2.0
