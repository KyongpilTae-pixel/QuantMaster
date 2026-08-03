# -*- coding: utf-8 -*-
"""
tests/test_auto_publish.py
auto_publish.py 날짜 헬퍼 + 영속 상태 I/O 단위 테스트
"""

import json
import os
import sys
import tempfile
from datetime import date

import pytest

# quantletter 디렉토리를 sys.path에 추가
QUANT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUANTLETTER_DIR = os.path.join(QUANT_DIR, "quantletter")
if QUANTLETTER_DIR not in sys.path:
    sys.path.insert(0, QUANTLETTER_DIR)


# ── auto_publish 함수 임포트 ───────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _patch_log_file(tmp_path, monkeypatch):
    """로그 파일/출력 디렉토리를 임시 디렉토리로 치환."""
    monkeypatch.setenv("_AP_TEST_MODE", "1")
    # OUT_DIR이 없으면 생성이 실패하므로 tmp_path를 OUT_DIR로 교체
    import auto_publish as ap
    monkeypatch.setattr(ap, "OUT_DIR",    str(tmp_path))
    monkeypatch.setattr(ap, "LOG_FILE",   str(tmp_path / "publish.log"))
    monkeypatch.setattr(ap, "LEDGER_KR",  str(tmp_path / "ledger_kr.json"))
    monkeypatch.setattr(ap, "LEDGER_US",  str(tmp_path / "ledger_us.json"))
    monkeypatch.setattr(ap, "PICKS_HIST", str(tmp_path / "picks_history.json"))


def import_ap():
    import auto_publish as ap
    return ap


# ── is_friday ─────────────────────────────────────────────────────────────

class TestIsFriday:
    def test_known_friday(self):
        ap = import_ap()
        assert ap.is_friday(date(2026, 7, 3)) is True   # 금요일

    def test_monday_not_friday(self):
        ap = import_ap()
        assert ap.is_friday(date(2026, 7, 6)) is False  # 월요일

    def test_all_weekdays(self):
        ap = import_ap()
        # 2026-07-06(월) ~ 07-12(일)
        expected = [False, False, False, False, True, False, False]
        for i, d in enumerate(range(6, 13)):
            assert ap.is_friday(date(2026, 7, d)) is expected[i], f"day={d}"


# ── is_first_friday_of_month ──────────────────────────────────────────────

class TestIsFirstFridayOfMonth:
    def test_first_friday_july_2026(self):
        ap = import_ap()
        assert ap.is_first_friday_of_month(date(2026, 7, 3)) is True

    def test_second_friday_not_first(self):
        ap = import_ap()
        assert ap.is_first_friday_of_month(date(2026, 7, 10)) is False

    def test_first_friday_august_2026(self):
        ap = import_ap()
        # 2026-08-07 is Friday and day 7
        assert ap.is_first_friday_of_month(date(2026, 8, 7)) is True

    def test_friday_day_8_not_first(self):
        ap = import_ap()
        # day=8이면 첫째 금요일 아님
        # 2026-01-09 is a Friday, day=9
        assert ap.is_first_friday_of_month(date(2026, 1, 9)) is False

    def test_non_friday_early_in_month(self):
        ap = import_ap()
        assert ap.is_first_friday_of_month(date(2026, 7, 1)) is False  # Wednesday


# ── last_friday_on_or_before ──────────────────────────────────────────────

class TestLastFridayOnOrBefore:
    def test_friday_returns_itself(self):
        ap = import_ap()
        d = date(2026, 7, 24)   # 금요일
        assert ap.last_friday_on_or_before(d) == date(2026, 7, 24)

    def test_saturday_returns_previous_friday(self):
        ap = import_ap()
        assert ap.last_friday_on_or_before(date(2026, 7, 25)) == date(2026, 7, 24)

    def test_thursday_returns_last_week_friday(self):
        ap = import_ap()
        assert ap.last_friday_on_or_before(date(2026, 7, 23)) == date(2026, 7, 17)

    def test_monday_returns_previous_friday(self):
        ap = import_ap()
        assert ap.last_friday_on_or_before(date(2026, 7, 27)) == date(2026, 7, 24)

    def test_month_boundary(self):
        ap = import_ap()
        # 2026-08-01 (토) → 직전 금요일은 2026-07-31
        assert ap.last_friday_on_or_before(date(2026, 8, 1)) == date(2026, 7, 31)


# ── prev_month ────────────────────────────────────────────────────────────

class TestPrevMonth:
    def test_mid_year(self):
        ap = import_ap()
        assert ap.prev_month(date(2026, 7, 1)) == (2026, 6)

    def test_january_returns_december_prev_year(self):
        ap = import_ap()
        assert ap.prev_month(date(2026, 1, 15)) == (2025, 12)

    def test_december_returns_november(self):
        ap = import_ap()
        assert ap.prev_month(date(2026, 12, 1)) == (2026, 11)

    def test_february(self):
        ap = import_ap()
        assert ap.prev_month(date(2026, 2, 28)) == (2026, 1)


# ── load_json / save_json ─────────────────────────────────────────────────

class TestJsonPersistence:
    def test_load_missing_returns_default(self, tmp_path):
        ap = import_ap()
        result = ap.load_json(str(tmp_path / "nonexistent.json"), {"x": 1})
        assert result == {"x": 1}

    def test_save_then_load(self, tmp_path):
        ap = import_ap()
        path = str(tmp_path / "data.json")
        data = {"key": "value", "nums": [1, 2, 3]}
        ap.save_json(path, data)
        loaded = ap.load_json(path, {})
        assert loaded == data

    def test_unicode_roundtrip(self, tmp_path):
        ap = import_ap()
        path = str(tmp_path / "kr.json")
        data = {"종목": "삼성전자", "코드": "005930"}
        ap.save_json(path, data)
        loaded = ap.load_json(path, {})
        assert loaded["종목"] == "삼성전자"

    def test_save_overwrites(self, tmp_path):
        ap = import_ap()
        path = str(tmp_path / "overwrite.json")
        ap.save_json(path, {"v": 1})
        ap.save_json(path, {"v": 2})
        assert ap.load_json(path, {})["v"] == 2

    def test_load_empty_list_default(self, tmp_path):
        ap = import_ap()
        result = ap.load_json(str(tmp_path / "missing.json"), [])
        assert result == []


# ── 날짜 헬퍼 엣지케이스 ──────────────────────────────────────────────────

class TestEdgeCases:
    def test_last_friday_when_friday_is_day1(self):
        """달의 1일이 금요일인 경우."""
        ap = import_ap()
        d = date(2026, 5, 1)  # 2026-05-01 is a Friday
        assert ap.last_friday_on_or_before(d) == date(2026, 5, 1)

    def test_first_friday_when_friday_is_day1(self):
        """달의 1일이 금요일 → 첫째 금요일."""
        ap = import_ap()
        d = date(2026, 5, 1)
        assert ap.is_first_friday_of_month(d) is True

    def test_year_boundary_prev_month(self):
        ap = import_ap()
        y, m = ap.prev_month(date(2025, 1, 1))
        assert (y, m) == (2024, 12)

    def test_consecutive_fridays_distance(self):
        """연속 금요일은 7일 간격."""
        ap = import_ap()
        from datetime import timedelta
        d1 = date(2026, 7, 3)
        d2 = date(2026, 7, 10)
        assert ap.is_friday(d1) and ap.is_friday(d2)
        assert (d2 - d1).days == 7
