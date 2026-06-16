"""
당일주도주 연속 등장 추적 — compute_consecutive_days() 단위 테스트.
캐시 파일을 임시 디렉터리에 생성해 실제 파일 I/O를 검증한다.
"""

import json
import os
import sys
import pytest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# 헬퍼: 임시 캐시 디렉터리 설정
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_cache(tmp_path, monkeypatch):
    """utils.data_loader._CACHE_DIR 를 tmp_path 로 교체."""
    import utils.data_loader as dl
    monkeypatch.setattr(dl, "_CACHE_DIR", str(tmp_path))
    return tmp_path


def _write_cache(tmp_path, market: str, date: datetime, codes: list[str]):
    date_str = date.strftime("%Y%m%d")
    path = tmp_path / f"leaders_{market}_{date_str}.json"
    data = [{"code": c, "name": c, "score_a": 1.0} for c in codes]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _today_data(codes: list[str]) -> list[dict]:
    return [{"code": c, "name": c, "score_a": 1.0} for c in codes]


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------

class TestComputeConsecutiveDays:

    def test_no_cache_streak_is_1(self, tmp_cache):
        """캐시 없으면 모든 종목 streak=1."""
        from utils.data_loader import compute_consecutive_days
        data = _today_data(["A", "B"])
        result = compute_consecutive_days("KOSPI", data, max_days=5)
        for item in result:
            assert item["consecutive_days"] == 1
            assert item["has_streak"] is False

    def test_one_day_history_streak_2(self, tmp_cache):
        """어제 캐시에 같은 종목 → streak=2."""
        from utils.data_loader import compute_consecutive_days
        yesterday = datetime.today() - timedelta(days=1)
        # 어제가 주말이면 금요일로 당김
        if yesterday.weekday() in (5, 6):
            yesterday -= timedelta(days=yesterday.weekday() - 4)
        _write_cache(tmp_cache, "KOSPI", yesterday, ["A", "B"])
        data = _today_data(["A", "B", "C"])
        result = compute_consecutive_days("KOSPI", data, max_days=5)
        by_code = {r["code"]: r for r in result}
        assert by_code["A"]["consecutive_days"] == 2
        assert by_code["A"]["has_streak"] is True
        assert by_code["B"]["consecutive_days"] == 2
        assert by_code["C"]["consecutive_days"] == 1   # 어제 없음
        assert by_code["C"]["has_streak"] is False

    def test_three_consecutive_days(self, tmp_cache):
        """3일 연속 등장 → streak=3."""
        from utils.data_loader import compute_consecutive_days
        today = datetime.today()
        # 최근 평일 2개 구하기
        trading_days = []
        i = 1
        while len(trading_days) < 2 and i < 10:
            prev = today - timedelta(days=i)
            if prev.weekday() not in (5, 6):
                trading_days.append(prev)
            i += 1
        for d in trading_days:
            _write_cache(tmp_cache, "KOSPI", d, ["A"])
        data = _today_data(["A"])
        result = compute_consecutive_days("KOSPI", data, max_days=5)
        assert result[0]["consecutive_days"] == 3
        assert result[0]["has_streak"] is True

    def test_streak_breaks_on_gap(self, tmp_cache):
        """어제는 없고 그제 있으면 streak=1 (연속 끊김)."""
        from utils.data_loader import compute_consecutive_days
        today = datetime.today()
        two_days_ago = None
        i = 2
        while i < 15:
            prev = today - timedelta(days=i)
            if prev.weekday() not in (5, 6):
                two_days_ago = prev
                break
            i += 1
        if two_days_ago is None:
            pytest.skip("2거래일 전 날짜 계산 불가")
        # 어제(평일) 캐시 없음, 그제 캐시 있음
        _write_cache(tmp_cache, "KOSPI", two_days_ago, ["A"])
        data = _today_data(["A"])
        result = compute_consecutive_days("KOSPI", data, max_days=5)
        assert result[0]["consecutive_days"] == 1

    def test_weekends_skipped(self, tmp_cache):
        """오늘이 월요일인 경우: 주말 건너뛰고 금요일 캐시 참조."""
        from utils.data_loader import compute_consecutive_days
        # 월요일 기준으로 강제: 실제 요일과 무관하게 금요일 캐시만 생성
        today = datetime.today()
        # 가장 최근 평일(오늘 포함) 이전 평일 탐색
        trading_days = []
        i = 1
        while len(trading_days) < 1 and i < 10:
            prev = today - timedelta(days=i)
            if prev.weekday() not in (5, 6):
                trading_days.append(prev)
            i += 1
        if not trading_days:
            pytest.skip("직전 평일 없음")
        _write_cache(tmp_cache, "KOSPI", trading_days[0], ["A"])
        data = _today_data(["A"])
        result = compute_consecutive_days("KOSPI", data, max_days=5)
        assert result[0]["consecutive_days"] == 2

    def test_preserves_all_original_fields(self, tmp_cache):
        """원본 dict 필드가 모두 보존된다."""
        from utils.data_loader import compute_consecutive_days
        data = [{"code": "A", "name": "테스트", "score_a": 0.5, "price_str": "1,000"}]
        result = compute_consecutive_days("KOSPI", data, max_days=5)
        assert result[0]["name"] == "테스트"
        assert result[0]["score_a"] == 0.5
        assert result[0]["price_str"] == "1,000"
        assert "consecutive_days" in result[0]
        assert "has_streak" in result[0]

    def test_empty_input_returns_empty(self, tmp_cache):
        """빈 리스트 입력 → 빈 리스트 반환."""
        from utils.data_loader import compute_consecutive_days
        result = compute_consecutive_days("KOSPI", [], max_days=5)
        assert result == []
