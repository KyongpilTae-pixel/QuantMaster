"""tests/test_infinite_loop_guards.py — 타임아웃/루프 탈출 조건 단위 테스트."""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import concurrent.futures
import time
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# dividend_scanner — ThreadPoolExecutor 배치 타임아웃 (30s wall-clock)
# ---------------------------------------------------------------------------


class TestDividendScannerBatchTimeout:
    def test_slow_yfinance_does_not_hang_indefinitely(self):
        """_scan_us_dividend 의 concurrent.futures.wait(timeout=30) 검증.

        _us_dividend_info 가 느리게 실행되더라도 wait(timeout=30) 내에서
        완료된 결과만 수집하고 반환해야 한다.
        """
        from utils.dividend_scanner import _scan_us_dividend

        def slow_info(sym):
            if sym == "SLOW":
                time.sleep(0.3)
            return {
                "name": sym, "symbol": sym, "market": "SP500",
                "price": 100.0, "div_yield": 4.0, "payout_ratio": 40.0,
                "div_growing": True, "mktcap_b": 100.0, "is_us": True,
            }

        listing = pd.DataFrame({"Symbol": ["AAPL", "SLOW", "JNJ"]})

        with patch("utils.dividend_scanner.fdr.StockListing", return_value=listing), \
             patch("utils.dividend_scanner._us_dividend_info", side_effect=slow_info):
            start = time.monotonic()
            results = _scan_us_dividend("SP500", min_yield_pct=0.0,
                                         max_payout_pct=100.0, top_n=30)
            elapsed = time.monotonic() - start

        assert elapsed < 5.0, f"배치 실행이 너무 오래 걸림: {elapsed:.2f}s"
        assert len(results) >= 1

    def test_fdr_listing_timeout_falls_through_to_empty(self):
        """fdr.StockListing 이 15초 이상 걸리면 빈 결과를 반환해야 한다."""
        from utils.dividend_scanner import _scan_us_dividend

        # ThreadPoolExecutor.result(timeout=15) 가 TimeoutError를 던지도록 모킹
        mock_future = MagicMock()
        mock_future.result.side_effect = concurrent.futures.TimeoutError("timeout")
        mock_executor = MagicMock()
        mock_executor.__enter__ = MagicMock(return_value=mock_executor)
        mock_executor.__exit__ = MagicMock(return_value=False)
        mock_executor.submit.return_value = mock_future

        with patch("utils.dividend_scanner.ThreadPoolExecutor",
                   return_value=mock_executor):
            results = _scan_us_dividend("SP500", 3.0, 70.0, 30)

        assert results == []


# ---------------------------------------------------------------------------
# scan_results_tracker — _trading_days_between 루프 없음 검증
# ---------------------------------------------------------------------------


class TestTradingDaysBetween:
    def test_returns_int(self):
        from utils.scan_results_tracker import _trading_days_between
        result = _trading_days_between("2026-01-01")
        assert isinstance(result, int)
        assert result >= 0

    def test_future_date_returns_zero(self):
        from utils.scan_results_tracker import _trading_days_between
        result = _trading_days_between("2099-12-31")
        assert result == 0

    def test_yesterday_returns_small_number(self):
        from utils.scan_results_tracker import _trading_days_between
        from datetime import datetime, timedelta
        yesterday = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        result = _trading_days_between(yesterday)
        # 어제부터 오늘까지 = 0 or 1 거래일
        assert result <= 2

    def test_invalid_date_returns_zero_not_crash(self):
        from utils.scan_results_tracker import _trading_days_between
        result = _trading_days_between("not-a-date")
        assert result == 0

    def test_4weeks_ago_reasonable_range(self):
        from utils.scan_results_tracker import _trading_days_between
        from datetime import datetime, timedelta
        four_weeks = (datetime.today() - timedelta(days=28)).strftime("%Y-%m-%d")
        result = _trading_days_between(four_weeks)
        # 4주 ≈ 20 거래일 ± 여유
        assert 15 <= result <= 25


# ---------------------------------------------------------------------------
# data_loader — requests.get timeout 파라미터 존재 여부 확인
# ---------------------------------------------------------------------------


class TestNaverRequestTimeout:
    def test_requests_called_with_timeout(self):
        """_naver_investor_trading 이 requests.get 에 timeout 인자를 전달하는지 확인."""
        from utils.data_loader import QuantDataLoader
        loader = QuantDataLoader()

        captured_kwargs = {}

        def capturing_get(url, **kwargs):
            captured_kwargs.update(kwargs)
            mock = MagicMock()
            mock.text = '<html><body><table class="type2"></table></body></html>'
            return mock

        with patch("utils.data_loader.requests.get", side_effect=capturing_get):
            loader._naver_investor_trading("005930", lookback_days=5)

        assert "timeout" in captured_kwargs, "requests.get에 timeout 인자 누락"
        assert captured_kwargs["timeout"] > 0


# ---------------------------------------------------------------------------
# momentum_scanner — scipy SLSQP maxiter 존재 여부
# ---------------------------------------------------------------------------


class TestRiskParityMaxiter:
    def test_minimize_called_with_maxiter(self):
        """Risk Parity scipy.minimize 호출 시 maxiter 가 있어야 한다."""
        try:
            import scipy  # noqa: F401
        except ImportError:
            pytest.skip("scipy 미설치")

        from utils.momentum_scanner import fetch_momentum_data
        from unittest.mock import patch as mp
        import numpy as np

        minimize_calls = []

        def capture_minimize(fn, w0, **kwargs):
            minimize_calls.append(kwargs)
            # 단순한 등가중 가중치를 성공 결과로 반환
            n = len(w0)
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.x = np.full(n, 1.0 / n)
            return mock_result

        sector_df = pd.DataFrame({
            "sector": ["IT", "금융", "에너지"],
            "ret_1m": [0.05, 0.03, 0.02],
            "name":   ["삼성전자", "KB금융", "SK이노"],
            "code":   ["005930", "105560", "096770"],
        })

        with mp("utils.momentum_scanner.minimize", side_effect=capture_minimize):
            try:
                fetch_momentum_data("KOSPI")
            except Exception:
                pass  # 네트워크 없을 때 일부 섹션은 실패해도 됨

        if minimize_calls:
            opts = minimize_calls[0].get("options", {})
            assert "maxiter" in opts, "maxiter 옵션 누락 — 수렴 실패 시 무한 루프 위험"
            assert opts["maxiter"] > 0
