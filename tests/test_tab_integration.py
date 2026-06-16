"""
탭별 통합 테스트 — 각 탭의 핵심 백엔드 함수가 올바른 구조를 반환하는지 검증.
실제 네트워크 호출이 필요합니다.

실행:
    pytest tests/test_tab_integration.py -m integration -v
    pytest tests/test_tab_integration.py -m integration -v -k "momentum"
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────
# 공통 bool 플래그 필수 필드 검증 헬퍼
# ─────────────────────────────────────────────

def _check_bool_flags(item: dict, flags: list[str], context: str = ""):
    for flag in flags:
        assert flag in item, f"[{context}] bool 플래그 '{flag}' 누락"
        assert isinstance(item[flag], bool), f"[{context}] '{flag}'가 bool이 아님: {type(item[flag])}"


# ─────────────────────────────────────────────
# 탭 1 — 시장모멘텀
# ─────────────────────────────────────────────

class TestMomentumTab:
    """utils/momentum_scanner.fetch_momentum_data()"""

    @pytest.fixture(scope="class")
    def data(self):
        from utils.momentum_scanner import fetch_momentum_data
        return fetch_momentum_data()

    def test_returns_dict(self, data):
        assert isinstance(data, dict)

    def test_has_rows(self, data):
        assert "rows" in data
        assert isinstance(data["rows"], list)
        assert len(data["rows"]) > 0

    def test_row_structure(self, data):
        row = data["rows"][0]
        required = ["key", "name", "ret_1m", "ret_3m", "ret_6m", "ret_12m",
                    "ret_1m_str", "ret_3m_str", "ret_6m_str", "ret_12m_str",
                    "win_1m", "win_3m", "win_6m", "win_12m",
                    "pos_1m", "pos_3m", "pos_6m", "pos_12m"]
        for field in required:
            assert field in row, f"필드 '{field}' 누락"

    def test_bool_flags(self, data):
        for row in data["rows"]:
            _check_bool_flags(row, ["win_1m", "win_3m", "win_6m", "win_12m",
                                    "pos_1m", "pos_3m", "pos_6m", "pos_12m"],
                              context=row.get("key", "?"))

    def test_has_recommendation_keys(self, data):
        for key in ["momentum_rec_name", "vaa_rec_name", "ma_rec_name"]:
            assert key in data, f"추천 키 '{key}' 누락"

    def test_no_error(self, data):
        assert data.get("error", "") == "", f"오류 발생: {data.get('error')}"


# ─────────────────────────────────────────────
# 탭 2 — 당일주도주
# ─────────────────────────────────────────────

class TestLeadersTab:
    """utils/data_loader.fetch_leaders_combined()"""

    @pytest.fixture(scope="class")
    def kospi_data(self):
        from utils.data_loader import fetch_leaders_combined
        return fetch_leaders_combined("KOSPI", top_n=10)

    @pytest.fixture(scope="class")
    def us_data(self):
        from utils.data_loader import fetch_leaders_combined
        return fetch_leaders_combined("US", top_n=5)

    def test_kospi_returns_list(self, kospi_data):
        assert isinstance(kospi_data, list)
        assert len(kospi_data) > 0

    def test_kospi_item_required_fields(self, kospi_data):
        item = kospi_data[0]
        required = ["code", "name", "price_str", "change_pct_str", "change_pct_val",
                    "score_a_str", "mktcap_str", "is_etf", "is_near_high",
                    "has_vol_rank", "has_rise_rank", "change_positive",
                    "has_score_b", "is_us"]
        for f in required:
            assert f in item, f"KOSPI 필드 '{f}' 누락"

    def test_kospi_bool_flags(self, kospi_data):
        flags = ["is_etf", "is_near_high", "has_vol_rank", "has_rise_rank",
                 "change_positive", "has_score_b", "is_us"]
        for item in kospi_data:
            _check_bool_flags(item, flags, context=item.get("name", "?"))

    def test_us_returns_list(self, us_data):
        assert isinstance(us_data, list)
        assert len(us_data) > 0

    def test_us_item_is_us_flag(self, us_data):
        for item in us_data:
            assert item.get("is_us") is True, f"US 종목 is_us=True 아님: {item.get('name')}"

    def test_etf_filter_consistency(self, kospi_data):
        for item in kospi_data:
            assert isinstance(item["is_etf"], bool)


# ─────────────────────────────────────────────
# 탭 3 — 스캐너
# ─────────────────────────────────────────────

class TestScannerTab:
    """scanner.QuantScanner — 초기화 + 최소 스캔 가능 여부"""

    def test_scanner_instantiable(self):
        from scanner import QuantScanner
        s = QuantScanner()
        assert s is not None
        assert hasattr(s, "run_advanced_scan")

    def test_kr_stock_listing_fallback(self):
        """KRX 404 대응: fdr 실패해도 fetch_kr_stock_listing이 데이터 반환."""
        from utils.data_loader import fetch_kr_stock_listing
        df = fetch_kr_stock_listing("KOSPI", min_mktcap_eok=10_000)
        assert df is not None
        # 빈 DataFrame이어도 오류 없어야 함
        assert hasattr(df, "columns")

    def test_kr_symbol_search_by_code(self):
        """6자리 코드 직접 조회 — fdr 실패해도 fallback 동작."""
        from utils.data_loader import _search_kr_symbol
        code, market = _search_kr_symbol("005930")
        assert code == "005930"
        assert market in ("KOSPI", "KOSDAQ")

    def test_kr_symbol_search_by_name(self):
        from utils.data_loader import _search_kr_symbol
        code, market = _search_kr_symbol("삼성전자")
        assert code != "", "삼성전자 코드 조회 실패"


# ─────────────────────────────────────────────
# 탭 4 — 분석 (OHLCV + 지표)
# ─────────────────────────────────────────────

class TestAnalysisTab:
    """utils/data_loader.fetch_stock_info() + OHLCV"""

    def test_kr_stock_info(self):
        from utils.data_loader import fetch_stock_info
        info = fetch_stock_info("005930", "KOSPI")
        assert isinstance(info, dict)
        assert "name" in info or "error" not in info

    def test_ohlcv_kr(self):
        import FinanceDataReader as fdr
        from datetime import datetime, timedelta
        end = datetime.today()
        start = end - timedelta(days=60)
        df = fdr.DataReader("005930", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        assert not df.empty
        assert "Close" in df.columns

    def test_vwap_calculation(self):
        from utils.indicators import compute_vwap
        import numpy as np, pandas as pd
        n = 30
        close = 10000 + np.cumsum(np.random.randn(n) * 100)
        df = pd.DataFrame({
            "Open": close * 0.99, "High": close * 1.01,
            "Low": close * 0.98, "Close": close,
            "Volume": np.random.randint(100_000, 500_000, n).astype(float),
        }, index=pd.date_range("2024-01-01", periods=n, freq="B"))
        vwap = compute_vwap(df, period=20)
        assert vwap is not None
        assert vwap > 0


# ─────────────────────────────────────────────
# 탭 5 — 종목조회
# ─────────────────────────────────────────────

class TestLookupTab:
    """NAVER 펀더멘털 + ETF 분석"""

    def test_kr_fundamentals(self):
        from utils.data_loader import _fetch_kr_naver_fundamentals
        result = _fetch_kr_naver_fundamentals("005930")
        assert result is not None
        assert isinstance(result, dict)
        assert "nv" in result or "sv" in result

    def test_etf_analysis(self):
        from utils.data_loader import fetch_etf_analysis
        # KODEX 200
        result = fetch_etf_analysis("069500")
        assert isinstance(result, dict)
        assert "base_index" in result or "error" in result

    def test_us_stock_info(self):
        from utils.data_loader import fetch_stock_info
        info = fetch_stock_info("AAPL", "SP500")
        assert isinstance(info, dict)


# ─────────────────────────────────────────────
# 탭 6 — 포트폴리오 (DB)
# ─────────────────────────────────────────────

class TestPortfolioTab:
    """utils/scan_db — 보유종목 CRUD"""

    def test_load_holdings_returns_list(self):
        from utils.scan_db import load_holdings
        result = load_holdings()
        assert isinstance(result, list)

    def test_is_holding_check(self):
        from utils.scan_db import is_holding
        # 존재 여부와 상관없이 bool 반환해야 함
        result = is_holding("999999")
        assert isinstance(result, bool)


# ─────────────────────────────────────────────
# 탭 7 — 히스토리 (DB)
# ─────────────────────────────────────────────

class TestHistoryTab:
    """utils/scan_db — 스캔 히스토리"""

    def test_load_run_list_returns_list(self):
        from utils.scan_db import load_run_list
        result = load_run_list()
        assert isinstance(result, list)

    def test_run_list_item_structure(self):
        from utils.scan_db import load_run_list
        runs = load_run_list()
        if runs:
            item = runs[0]
            for field in ["run_id", "label", "market", "scan_count"]:
                assert field in item, f"run_list 필드 '{field}' 누락"


# ─────────────────────────────────────────────
# 스캐너 — 하락방어 모드
# ─────────────────────────────────────────────

class TestDefensiveScannerTab:
    """utils/defensive_scanner — 하락방어 스캔"""

    def test_fetch_kr_stock_listing_for_defensive(self):
        """하락방어 스캔용 KR 종목 목록 조회 (fdr 404 fallback 포함)."""
        from utils.data_loader import fetch_kr_stock_listing
        df = fetch_kr_stock_listing("KOSPI", min_mktcap_eok=10_000)
        assert df is not None

    def test_defensive_scan_small(self):
        """시총 상위 5개만으로 소규모 스캔 실행."""
        from utils.defensive_scanner import scan_defensive_stocks
        results = scan_defensive_stocks(
            market="KOSPI",
            period_days=20,
            max_beta=1.5,
            min_mktcap_eok=50_000,
            top_n=5,
        )
        assert isinstance(results, list)
        for r in results:
            _check_bool_flags(r, ["rs_positive", "dc_good"], context=r.get("name", "?"))
