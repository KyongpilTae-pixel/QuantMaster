"""utils/scan_db 단위 테스트 (임시 DB 사용, 네트워크 불필요)."""

import math
import pytest
from pathlib import Path
from unittest.mock import patch

import utils.scan_db as scan_db


# ---------------------------------------------------------------------------
# 헬퍼 / Fixtures
# ---------------------------------------------------------------------------


class _FakeResult:
    """ScanResult 필드를 흉내 내는 간단한 객체."""
    def __init__(self, name, symbol, **kwargs):
        self.name = name
        self.symbol = symbol
        self.market_raw = kwargs.get("market_raw", "KOSPI")
        self.pbr = kwargs.get("pbr", 0.8)
        self.psr = kwargs.get("psr", 1.2)
        self.div_yield = kwargs.get("div_yield", "1.50%")
        self.mfi = kwargs.get("mfi", 55.0)
        self.obv_ok = kwargs.get("obv_ok", True)
        self.vwap_price = kwargs.get("vwap_price", 10_000.0)
        self.close = kwargs.get("close", 11_000.0)
        self.vwap_gap = kwargs.get("vwap_gap", 10.0)
        self.condition = kwargs.get("condition", "원본")
        self.applied_pbr = kwargs.get("applied_pbr", 1.2)
        self.applied_gpa = kwargs.get("applied_gpa", 0.6)
        self.applied_mfi = kwargs.get("applied_mfi", 50)
        self.applied_obv = kwargs.get("applied_obv", True)
        self.applied_min_cap = kwargs.get("applied_min_cap", "전체")
        self.currency = kwargs.get("currency", "KRW")
        self.market_cap_str = kwargs.get("market_cap_str", "10,000억")


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """각 테스트마다 임시 DB 경로를 사용."""
    db_file = tmp_path / "test_history.db"
    monkeypatch.setattr(scan_db, "DB_PATH", db_file)
    return db_file


@pytest.fixture
def two_results():
    return [
        _FakeResult("삼성전자", "005930", pbr=0.9, mfi=60.0),
        _FakeResult("SK하이닉스", "000660", pbr=1.1, mfi=52.0, div_yield="-"),
    ]


@pytest.fixture
def saved_run_id(two_results):
    """기본 스캔 1건 저장 후 run_id 반환."""
    return scan_db.save_scan(
        market="KOSPI",
        vwap_period=120,
        target_pbr=1.2,
        min_cap_label="전체",
        results=two_results,
    )


# ---------------------------------------------------------------------------
# save_scan
# ---------------------------------------------------------------------------


def test_save_scan_returns_positive_int(two_results):
    run_id = scan_db.save_scan("KOSPI", 120, 1.2, "전체", two_results)
    assert isinstance(run_id, int) and run_id > 0


def test_save_scan_increments_id(two_results):
    id1 = scan_db.save_scan("KOSPI", 120, 1.2, "전체", two_results)
    id2 = scan_db.save_scan("KOSDAQ", 60, 1.5, "소형주+", two_results)
    assert id2 > id1


def test_save_scan_empty_results():
    run_id = scan_db.save_scan("KOSPI", 120, 1.2, "전체", [])
    assert run_id > 0


# ---------------------------------------------------------------------------
# load_run_list
# ---------------------------------------------------------------------------


def test_load_run_list_empty_when_no_data():
    runs = scan_db.load_run_list()
    assert runs == []


def test_load_run_list_returns_saved_run(saved_run_id):
    runs = scan_db.load_run_list()
    assert len(runs) == 1


def test_load_run_list_id_matches(saved_run_id):
    runs = scan_db.load_run_list()
    assert runs[0]["id"] == str(saved_run_id)


def test_load_run_list_label_contains_market(saved_run_id):
    runs = scan_db.load_run_list()
    assert "KOSPI" in runs[0]["label"]


def test_load_run_list_label_contains_vwap(saved_run_id):
    runs = scan_db.load_run_list()
    assert "VWAP120" in runs[0]["label"]


def test_load_run_list_label_contains_result_count(saved_run_id):
    runs = scan_db.load_run_list()
    assert "2종목" in runs[0]["label"]


def test_load_run_list_newest_first(two_results):
    id1 = scan_db.save_scan("KOSPI", 120, 1.2, "전체", two_results)
    id2 = scan_db.save_scan("NASDAQ", 60, 1.5, "전체", two_results)
    runs = scan_db.load_run_list()
    assert runs[0]["id"] == str(id2)  # 최신순
    assert runs[1]["id"] == str(id1)


def test_load_run_list_multiple_runs(two_results):
    for market in ("KOSPI", "KOSDAQ", "SP500"):
        scan_db.save_scan(market, 120, 1.2, "전체", two_results)
    runs = scan_db.load_run_list()
    assert len(runs) == 3


# ---------------------------------------------------------------------------
# load_scan_results
# ---------------------------------------------------------------------------


def test_load_scan_results_count(saved_run_id):
    results = scan_db.load_scan_results(saved_run_id)
    assert len(results) == 2


def test_load_scan_results_name(saved_run_id):
    results = scan_db.load_scan_results(saved_run_id)
    names = {r["name"] for r in results}
    assert "삼성전자" in names and "SK하이닉스" in names


def test_load_scan_results_pbr(saved_run_id):
    results = scan_db.load_scan_results(saved_run_id)
    samsung = next(r for r in results if r["name"] == "삼성전자")
    assert abs(samsung["pbr"] - 0.9) < 1e-6


def test_load_scan_results_mfi(saved_run_id):
    results = scan_db.load_scan_results(saved_run_id)
    samsung = next(r for r in results if r["name"] == "삼성전자")
    assert abs(samsung["mfi"] - 60.0) < 1e-6


def test_load_scan_results_obv_ok_bool(saved_run_id):
    results = scan_db.load_scan_results(saved_run_id)
    for r in results:
        assert isinstance(r["obv_ok"], bool)


def test_load_scan_results_div_yield(saved_run_id):
    results = scan_db.load_scan_results(saved_run_id)
    samsung = next(r for r in results if r["name"] == "삼성전자")
    assert samsung["div_yield"] == "1.50%"


def test_load_scan_results_empty_for_unknown_run():
    results = scan_db.load_scan_results(99999)
    assert results == []


def test_load_scan_results_currency(two_results):
    us_results = [_FakeResult("Apple", "AAPL", currency="USD", market_raw="SP500")]
    run_id = scan_db.save_scan("SP500", 120, 1.5, "전체", us_results)
    results = scan_db.load_scan_results(run_id)
    assert results[0]["currency"] == "USD"


def test_load_scan_results_applied_obv_bool(saved_run_id):
    results = scan_db.load_scan_results(saved_run_id)
    for r in results:
        assert isinstance(r["applied_obv"], bool)


# ---------------------------------------------------------------------------
# WhaleScanResult 헬퍼
# ---------------------------------------------------------------------------


class _FakeWhaleResult:
    """WhaleScanResult 필드를 흉내 내는 간단한 객체."""
    def __init__(self, name, symbol, **kwargs):
        self.name = name
        self.symbol = symbol
        self.market = kwargs.get("market", "KOSPI")
        self.signal_date = kwargs.get("signal_date", "2024-01-15")
        self.score = kwargs.get("score", 60)
        self.signal_type = kwargs.get("signal_type", "매집봉+돌파")
        self.obv_spike = kwargs.get("obv_spike", True)
        self.breakout = kwargs.get("breakout", True)
        self.alpha = kwargs.get("alpha", False)
        self.short_cover = kwargs.get("short_cover", False)
        self.close = kwargs.get("close", 50_000.0)
        self.volume_ratio = kwargs.get("volume_ratio", 2.5)
        self.applied_step = kwargs.get("applied_step", "원본")


@pytest.fixture
def two_whale_results():
    return [
        _FakeWhaleResult("삼성전자", "005930", score=90, breakout=True, alpha=True),
        _FakeWhaleResult("SK하이닉스", "000660", score=60, breakout=False),
    ]


@pytest.fixture
def saved_whale_run_id(two_whale_results):
    return scan_db.save_whale_scan(market="KOSPI", results=two_whale_results)


# ---------------------------------------------------------------------------
# save_whale_scan
# ---------------------------------------------------------------------------


def test_save_whale_scan_returns_positive_int(two_whale_results):
    run_id = scan_db.save_whale_scan("KOSPI", two_whale_results)
    assert isinstance(run_id, int) and run_id > 0


def test_save_whale_scan_increments_id(two_whale_results):
    id1 = scan_db.save_whale_scan("KOSPI", two_whale_results)
    id2 = scan_db.save_whale_scan("KOSDAQ", two_whale_results)
    assert id2 > id1


def test_save_whale_scan_empty_results():
    run_id = scan_db.save_whale_scan("KOSPI", [])
    assert run_id > 0


def test_save_whale_scan_mode_is_whale(two_whale_results):
    run_id = scan_db.save_whale_scan("KOSPI", two_whale_results)
    mode = scan_db.get_run_mode(run_id)
    assert mode == "whale"


# ---------------------------------------------------------------------------
# get_run_mode
# ---------------------------------------------------------------------------


def test_get_run_mode_quant(saved_run_id):
    assert scan_db.get_run_mode(saved_run_id) == "quant"


def test_get_run_mode_whale(saved_whale_run_id):
    assert scan_db.get_run_mode(saved_whale_run_id) == "whale"


def test_get_run_mode_unknown_id_returns_quant():
    assert scan_db.get_run_mode(99999) == "quant"


# ---------------------------------------------------------------------------
# load_whale_results
# ---------------------------------------------------------------------------


def test_load_whale_results_count(saved_whale_run_id):
    results = scan_db.load_whale_results(saved_whale_run_id)
    assert len(results) == 2


def test_load_whale_results_names(saved_whale_run_id):
    results = scan_db.load_whale_results(saved_whale_run_id)
    names = {r["name"] for r in results}
    assert "삼성전자" in names and "SK하이닉스" in names


def test_load_whale_results_sorted_by_score_desc(saved_whale_run_id):
    results = scan_db.load_whale_results(saved_whale_run_id)
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_load_whale_results_breakout_bool(saved_whale_run_id):
    results = scan_db.load_whale_results(saved_whale_run_id)
    for r in results:
        assert isinstance(r["breakout"], bool)


def test_load_whale_results_breakout_value(saved_whale_run_id):
    results = scan_db.load_whale_results(saved_whale_run_id)
    samsung = next(r for r in results if r["name"] == "삼성전자")
    assert samsung["breakout"] is True
    sk = next(r for r in results if r["name"] == "SK하이닉스")
    assert sk["breakout"] is False


def test_load_whale_results_score(saved_whale_run_id):
    results = scan_db.load_whale_results(saved_whale_run_id)
    samsung = next(r for r in results if r["name"] == "삼성전자")
    assert samsung["score"] == 90


def test_load_whale_results_empty_for_unknown_run():
    results = scan_db.load_whale_results(99999)
    assert results == []


def test_load_whale_results_applied_step(saved_whale_run_id):
    results = scan_db.load_whale_results(saved_whale_run_id)
    for r in results:
        assert isinstance(r["applied_step"], str)


# ---------------------------------------------------------------------------
# load_run_list — whale 모드 레이블
# ---------------------------------------------------------------------------


def test_load_run_list_whale_label(two_whale_results):
    scan_db.save_whale_scan("KOSPI", two_whale_results)
    runs = scan_db.load_run_list()
    assert runs[0]["scan_mode"] == "whale"
    assert "세력탐지" in runs[0]["label"]
    assert "KOSPI" in runs[0]["label"]


def test_load_run_list_mixed_modes(two_results, two_whale_results):
    scan_db.save_scan("KOSPI", 120, 1.2, "전체", two_results)
    scan_db.save_whale_scan("KOSDAQ", two_whale_results)
    runs = scan_db.load_run_list()
    modes = {r["scan_mode"] for r in runs}
    assert modes == {"quant", "whale"}
