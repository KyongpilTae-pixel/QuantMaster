"""
섹터 모멘텀 스캐너 단위 테스트.
실제 네트워크 없이 _fetch_all_returns를 monkeypatch해 동작 검증.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ── 헬퍼 ────────────────────────────────────────────────────────────────────

def _make_rets(val: float | None = 5.0) -> dict:
    from utils.sector_scanner import PERIODS
    return {key: val for key, _, _ in PERIODS}


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
        for code, name, sector in KR_SECTORS:
            assert isinstance(code, str) and len(code) == 6
            assert isinstance(name, str)
            assert isinstance(sector, str)

    def test_us_sectors_ticker_format(self):
        from utils.sector_scanner import US_SECTORS
        for code, name, sector in US_SECTORS:
            assert code.isalpha()

    def test_periods_defined(self):
        from utils.sector_scanner import PERIODS
        assert len(PERIODS) == 5
        keys = [k for k, _, _ in PERIODS]
        assert keys == ["5d", "1m", "3m", "6m", "12m"]


# ── fetch_sector_momentum 반환 형식 테스트 ────────────────────────────────────

class TestFetchSectorMomentum:

    @pytest.fixture(autouse=True)
    def patch_fetch(self, monkeypatch):
        import utils.sector_scanner as ss
        from utils.sector_scanner import KR_SECTORS, US_SECTORS
        # 069500=10%, SPY=8%, 나머지 5%
        ret_map = {s[0]: 5.0 for s in KR_SECTORS + US_SECTORS}
        ret_map["069500"] = 10.0
        ret_map["SPY"] = 8.0

        def fake_fetch(code):
            v = ret_map.get(code, 2.0)
            from utils.sector_scanner import PERIODS
            return code, {key: v for key, _, _ in PERIODS}

        monkeypatch.setattr(ss, "_fetch_all_returns", fake_fetch)

    def test_returns_list(self):
        from utils.sector_scanner import fetch_sector_momentum
        assert isinstance(fetch_sector_momentum("KR"), list)

    def test_kr_length(self):
        from utils.sector_scanner import fetch_sector_momentum, KR_SECTORS
        assert len(fetch_sector_momentum("KR")) == len(KR_SECTORS)

    def test_us_length(self):
        from utils.sector_scanner import fetch_sector_momentum, US_SECTORS
        assert len(fetch_sector_momentum("US")) == len(US_SECTORS)

    def test_required_fields(self):
        from utils.sector_scanner import fetch_sector_momentum, PERIODS
        result = fetch_sector_momentum("KR")
        base = {"code", "name", "sector", "rank"}
        period_fields = {
            f"ret_{key}{sfx}"
            for key, _, _ in PERIODS
            for sfx in ("", "_str", "_positive", "_has_data")
        }
        required = base | period_fields
        for row in result:
            missing = required - row.keys()
            assert not missing, f"필드 누락: {missing}"

    def test_sorted_by_1m_descending(self):
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR")
        vals = [r["ret_1m"] for r in result]
        assert vals == sorted(vals, reverse=True)

    def test_rank_sequential(self):
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR")
        for i, row in enumerate(result):
            assert row["rank"] == i + 1

    def test_top_kr_is_069500(self):
        from utils.sector_scanner import fetch_sector_momentum
        assert fetch_sector_momentum("KR")[0]["code"] == "069500"

    def test_top_us_is_spy(self):
        from utils.sector_scanner import fetch_sector_momentum
        assert fetch_sector_momentum("US")[0]["code"] == "SPY"

    def test_all_periods_positive(self):
        from utils.sector_scanner import fetch_sector_momentum, PERIODS
        result = fetch_sector_momentum("KR")
        for row in result:
            for key, _, _ in PERIODS:
                assert row[f"ret_{key}_positive"] is True

    def test_ret_str_format(self):
        from utils.sector_scanner import fetch_sector_momentum, PERIODS
        result = fetch_sector_momentum("KR")
        for row in result:
            for key, _, _ in PERIODS:
                assert row[f"ret_{key}_str"].endswith("%")

    def test_no_period_param_needed(self):
        """fetch_sector_momentum은 period 인수 없이 호출 가능."""
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR")
        assert isinstance(result, list)


# ── None 수익률 처리 ──────────────────────────────────────────────────────────

class TestNoneReturnHandling:

    def test_none_return_has_data_false(self, monkeypatch):
        import utils.sector_scanner as ss
        from utils.sector_scanner import PERIODS
        monkeypatch.setattr(ss, "_fetch_all_returns",
                            lambda code: (code, {key: None for key, _, _ in PERIODS}))
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR")
        for row in result:
            for key, _, _ in PERIODS:
                assert row[f"ret_{key}_has_data"] is False
                assert row[f"ret_{key}_str"] == "-"

    def test_none_sorted_last(self, monkeypatch):
        import utils.sector_scanner as ss
        from utils.sector_scanner import KR_SECTORS, PERIODS
        first_code = KR_SECTORS[0][0]

        def mixed_fetch(code):
            if code == first_code:
                return code, {key: None for key, _, _ in PERIODS}
            return code, {key: 1.0 for key, _, _ in PERIODS}

        monkeypatch.setattr(ss, "_fetch_all_returns", mixed_fetch)
        from utils.sector_scanner import fetch_sector_momentum
        result = fetch_sector_momentum("KR")
        assert result[-1]["code"] == first_code
