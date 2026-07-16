"""tests/test_investor_trading.py — 외국인·기관 순매수 추적 단위+통합 테스트."""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# fixture
# ---------------------------------------------------------------------------


def _make_naver_html_response(rows=5):
    """NAVER 투자자별 매매동향 페이지 HTML 시뮬레이션."""
    tr_rows = ""
    for i in range(rows):
        date = f"2026.01.{i+1:02d}"
        # 외국인+, 기관-, 개인+
        tr_rows += f"""
        <tr>
            <td>{date}</td>
            <td class="num">100</td>
            <td class="num"><span class="nv2">+{(i+1)*1000:,}</span></td>
            <td class="num"><span class="nv2">+{(i+1)*500:,}</span></td>
            <td class="num"><span class="nv1">-{(i+1)*300:,}</span></td>
        </tr>"""
    return f"""<html><body>
        <table class="type2">
            <tr><th>날짜</th><th>체결량</th><th>외국인</th><th>기관합계</th><th>개인</th></tr>
            <tr><td colspan="5"></td></tr>
            {tr_rows}
        </table>
    </body></html>"""


# ---------------------------------------------------------------------------
# _naver_investor_trading 단위 테스트
# ---------------------------------------------------------------------------


class TestNaverInvestorTrading:
    def test_returns_expected_keys(self):
        from utils.data_loader import QuantDataLoader
        loader = QuantDataLoader()
        mock_resp = MagicMock()
        mock_resp.text = _make_naver_html_response(5)
        with patch("utils.data_loader.requests.get", return_value=mock_resp):
            result = loader._naver_investor_trading("005930", lookback_days=5)
        assert "rows" in result
        assert "cumulative" in result
        assert result["error"] is None

    def test_rows_count_limited_by_lookback(self):
        from utils.data_loader import QuantDataLoader
        loader = QuantDataLoader()
        mock_resp = MagicMock()
        mock_resp.text = _make_naver_html_response(10)
        with patch("utils.data_loader.requests.get", return_value=mock_resp):
            result = loader._naver_investor_trading("005930", lookback_days=3)
        assert len(result["rows"]) <= 3

    def test_cumulative_foreign_positive(self):
        from utils.data_loader import QuantDataLoader
        loader = QuantDataLoader()
        mock_resp = MagicMock()
        mock_resp.text = _make_naver_html_response(5)
        with patch("utils.data_loader.requests.get", return_value=mock_resp):
            result = loader._naver_investor_trading("005930", lookback_days=5)
        # 외국인 순매수가 모두 양수이므로 cumulative > 0
        assert result["cumulative"]["foreign"] > 0

    def test_network_error_returns_error_dict(self):
        from utils.data_loader import QuantDataLoader
        loader = QuantDataLoader()
        with patch("utils.data_loader.requests.get", side_effect=Exception("connection refused")):
            result = loader._naver_investor_trading("005930", lookback_days=5)
        assert "error" in result
        assert result["error"] is not None
        assert result["rows"] == []

    def test_table_not_found_returns_error(self):
        from utils.data_loader import QuantDataLoader
        loader = QuantDataLoader()
        mock_resp = MagicMock()
        mock_resp.text = "<html><body>no table here</body></html>"
        with patch("utils.data_loader.requests.get", return_value=mock_resp):
            result = loader._naver_investor_trading("005930", lookback_days=5)
        assert result["error"] is not None


# ---------------------------------------------------------------------------
# get_investor_trading 단위 테스트 (pykrx 우선 → NAVER 폴백)
# ---------------------------------------------------------------------------


class TestGetInvestorTrading:
    def _make_pykrx_df(self):
        """pykrx get_market_trading_volume_by_investor 반환 형식 시뮬레이션."""
        idx = pd.date_range("2026-01-02", periods=10, freq="B")
        return pd.DataFrame(
            {
                "외국인합계": [1_000] * 10,
                "기관합계":   [-500]  * 10,
                "개인":       [-500]  * 10,
            },
            index=idx,
        )

    def test_pykrx_success_path(self):
        from utils.data_loader import QuantDataLoader
        loader = QuantDataLoader()
        mock_df = self._make_pykrx_df()
        # pykrx 는 get_investor_trading 함수 내부에서 lazy import 됨
        # pykrx.stock 을 직접 패치
        with patch("pykrx.stock.get_market_trading_volume_by_investor",
                   return_value=mock_df):
            result = loader.get_investor_trading("005930", lookback_days=10)

        assert result["error"] is None
        assert len(result["rows"]) <= 10
        assert result["cumulative"]["foreign"] == 10_000

    def test_pykrx_failure_falls_back_to_naver(self):
        from utils.data_loader import QuantDataLoader
        loader = QuantDataLoader()
        fallback_result = {"rows": [{"date": "2026-01-02", "foreign_net": 100,
                                      "inst_net": -50, "retail_net": -50}],
                           "cumulative": {"foreign": 100, "inst": -50, "retail": -50},
                           "error": None}
        with patch("pykrx.stock.get_market_trading_volume_by_investor",
                   side_effect=Exception("pykrx 실패")), \
             patch.object(QuantDataLoader, "_naver_investor_trading",
                          return_value=fallback_result):
            result = loader.get_investor_trading("005930", lookback_days=5)

        assert result["error"] is None
        assert result["rows"][0]["date"] == "2026-01-02"

    def test_pykrx_empty_df_falls_back(self):
        from utils.data_loader import QuantDataLoader
        loader = QuantDataLoader()
        fallback_result = {"rows": [], "cumulative": {"foreign": 0, "inst": 0, "retail": 0},
                           "error": "데이터 없음"}
        with patch("pykrx.stock.get_market_trading_volume_by_investor",
                   return_value=pd.DataFrame()), \
             patch.object(QuantDataLoader, "_naver_investor_trading",
                          return_value=fallback_result):
            result = loader.get_investor_trading("005930", lookback_days=5)

        assert result["rows"] == []


# ---------------------------------------------------------------------------
# 무한 루프 방지 — _naver_investor_trading lookback 탈출 조건 검증
# ---------------------------------------------------------------------------


class TestNaverLoopSafety:
    def test_break_condition_fires_at_lookback(self):
        """100행 HTML이 있어도 lookback_days=3에서 멈춰야 한다."""
        from utils.data_loader import QuantDataLoader
        loader = QuantDataLoader()
        mock_resp = MagicMock()
        mock_resp.text = _make_naver_html_response(100)
        with patch("utils.data_loader.requests.get", return_value=mock_resp):
            result = loader._naver_investor_trading("005930", lookback_days=3)
        assert len(result["rows"]) <= 3

    def test_empty_rows_html_returns_empty_not_hang(self):
        """데이터 행이 없는 테이블에서 무한 루프 없이 빈 결과 반환."""
        from utils.data_loader import QuantDataLoader
        loader = QuantDataLoader()
        empty_html = '<html><body><table class="type2"><tr><th>날짜</th></tr></table></body></html>'
        mock_resp = MagicMock()
        mock_resp.text = empty_html
        with patch("utils.data_loader.requests.get", return_value=mock_resp):
            result = loader._naver_investor_trading("005930", lookback_days=5)
        assert result["rows"] == []


# ---------------------------------------------------------------------------
# 통합 테스트 (실제 네트워크 필요)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInvestorTradingIntegration:
    def test_real_kr_stock_returns_rows(self):
        from utils.data_loader import QuantDataLoader
        loader = QuantDataLoader()
        result = loader.get_investor_trading("005930", lookback_days=10)
        assert isinstance(result, dict)
        assert "rows" in result and "cumulative" in result
        # 실패해도 error 키가 있어야 함
        assert "error" in result

    def test_result_structure_matches_expected_schema(self):
        from utils.data_loader import QuantDataLoader
        loader = QuantDataLoader()
        result = loader.get_investor_trading("005930", lookback_days=5)
        for row in result.get("rows", []):
            assert "date" in row
            assert "foreign_net" in row
            assert "inst_net" in row
            assert "retail_net" in row
