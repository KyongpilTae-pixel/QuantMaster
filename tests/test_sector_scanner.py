"""
섹터 모멘텀 스캐너 단위 테스트.
실제 네트워크 없이 _fetch_return을 monkeypatch해 동작 검증.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch


# ── 헬퍼 ────────────────────────────────────────────────────────────────────

def _make_return_map(codes: list[str], ret: float | None = 5.0) -> dict[str, float | None]:
    """지정 코드 모두에 동일 수익률 할당."""
    return {c: ret for c in codes}


# ── 섹터 정의 테스트 ─────────────────────────────────────────────────────────

class TestSectorDefinitions:

    def test_kr_sectors_count(self):
        from utils.sector_scanner import KR_SECTORS
        assert len(KR_SECTORS) >= 10

    def test_us_sectors_count(self):
        from utils.sector_scanner import US_SECTORS
        assert len(US_SECTORS) >= 10

    def test_kr_sectors_tuple_structure(self):
        from utils.sector_scanner import KR_SECTORS
        for item in KR_SECTORS:
            code, name, sector = item
            assert isinstance(code, str) and len(code) == 6
            assert isinstance(name, str)
            assert isinstance(sector, str)

    def test_us_sectors_ticker_format(self):
        from utils.sector_scanner import US_SECTORS
        for code, name, sector in US_SECTORS:
            assert code.isalpha()  # SPY, XLK, ... — 알파벳만


# ── fetch_sector_momentum 반환 형식 테스트 ────────────────────────────────────

class TestFetchSectorMomentum:

    @pytest.fixture(autouse=True)
    def patch_fetch(self, monkeypatch):
        """_fetch_return 을 고정 수익률 반환 함수로 교체."""
        import utils.sector_scanner as ss
        from utils.sector_scanner import KR_SECTORS, US_SECTORS
        kr_codes = [s[0] for s in KR_SECTORS]
        us_codes = [s[0] for s in US_SECTORS]
        # KR: 069500=10%, 나머지 5%  /  US: SPY=8%, 나머지 3%
        ret_map = {c: 5.0 for c in kr_codes}
        ret_map["069500"] = 10.0
        ret_map.update({c: 3.0 for c in us_codes})
        ret_map["SPY"] = 8.0

        def fake_fetch(code, period_days):
            return code, ret_map.get(code, 2.0)

        monkeypatch.setattr(ss, "_fetch_return", fake_fetch)

    def test_returns_list(self):
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR", 20)
        assert isinstance(result, list)

    def test_kr_length(self):
        from utils.sector_scanner import fetch_sector_momentum, KR_SECTORS
        result = fetch_sector_momentum("KR", 20)
        assert len(result) == len(KR_SECTORS)

    def test_us_length(self):
        from utils.sector_scanner import fetch_sector_momentum, US_SECTORS
        result = fetch_sector_momentum("US", 20)
        assert len(result) == len(US_SECTORS)

    def test_required_fields(self):
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR", 20)
        required = {"code", "name", "sector", "ret_pct", "ret_str", "ret_positive", "has_data", "rank"}
        for row in result:
            assert required.issubset(row.keys()), f"필드 누락: {required - row.keys()}"

    def test_sorted_descending(self):
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR", 20)
        returns = [r["ret_pct"] for r in result]
        assert returns == sorted(returns, reverse=True)

    def test_rank_starts_at_1(self):
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR", 20)
        assert result[0]["rank"] == 1

    def test_rank_sequential(self):
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR", 20)
        for i, row in enumerate(result):
            assert row["rank"] == i + 1

    def test_top_kr_is_069500(self):
        """069500(KODEX 200)이 수익률 최고이므로 1위."""
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR", 20)
        assert result[0]["code"] == "069500"

    def test_top_us_is_spy(self):
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("US", 20)
        assert result[0]["code"] == "SPY"

    def test_ret_positive_flag_true(self):
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR", 20)
        assert all(r["ret_positive"] for r in result)   # 모두 양수

    def test_ret_str_format(self):
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR", 20)
        for row in result:
            assert row["ret_str"].endswith("%")


# ── None 수익률(데이터 없음) 처리 ─────────────────────────────────────────────

class TestNoneReturnHandling:

    def test_none_return_has_data_false(self, monkeypatch):
        import utils.sector_scanner as ss
        monkeypatch.setattr(ss, "_fetch_return", lambda code, days: (code, None))
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR", 20)
        for row in result:
            assert row["has_data"] is False
            assert row["ret_str"] == "-"

    def test_none_return_sorted_last(self, monkeypatch):
        """수익률 None 종목은 정렬 마지막(−999)."""
        import utils.sector_scanner as ss
        from utils.sector_scanner import KR_SECTORS
        call_count = [0]

        def mixed_fetch(code, days):
            call_count[0] += 1
            # 첫 번째 코드만 None
            if code == KR_SECTORS[0][0]:
                return code, None
            return code, 1.0

        monkeypatch.setattr(ss, "_fetch_return", mixed_fetch)
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR", 20)
        # None 항목은 맨 뒤
        assert result[-1]["code"] == KR_SECTORS[0][0]
        assert result[-1]["has_data"] is False
