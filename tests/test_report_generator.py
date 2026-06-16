"""
일별 HTML 리포트 자동 생성 — report_generator 단위 테스트.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _sample_data(market: str = "KOSPI") -> list[dict]:
    return [
        {
            "rank": 1, "code": "005930", "name": "삼성전자",
            "change_pct_str": "+5.3%", "change_pct_val": 5.3,
            "vol_rank_str": "1", "rise_rank_str": "2",
            "score_a_str": "1.500", "score_a": 1.5,
            "has_vol_rank": True, "has_rise_rank": True,
            "is_near_high": True, "consecutive_days": 3, "has_streak": True,
            "data_date": "2026-06-16 (월)",
        },
        {
            "rank": 2, "code": "000660", "name": "SK하이닉스",
            "change_pct_str": "+2.1%", "change_pct_val": 2.1,
            "vol_rank_str": "3", "rise_rank_str": "-",
            "score_a_str": "0.333", "score_a": 0.333,
            "has_vol_rank": True, "has_rise_rank": False,
            "is_near_high": False, "consecutive_days": 1, "has_streak": False,
            "data_date": "2026-06-16 (월)",
        },
        {
            "rank": 3, "code": "035420", "name": "NAVER",
            "change_pct_str": "+6.0%", "change_pct_val": 6.0,
            "vol_rank_str": "5", "rise_rank_str": "1",
            "score_a_str": "1.200", "score_a": 1.2,
            "has_vol_rank": True, "has_rise_rank": True,
            "is_near_high": True, "consecutive_days": 2, "has_streak": True,
            "data_date": "2026-06-16 (월)",
        },
    ]


@pytest.fixture()
def tmp_reports(tmp_path, monkeypatch):
    import utils.report_generator as rg
    monkeypatch.setattr(rg, "_REPORTS_DIR", str(tmp_path))
    return tmp_path


class TestGenerateMarketSection:

    def test_contains_header(self):
        from utils.report_generator import generate_market_section
        section = generate_market_section("KOSPI", _sample_data(), "11:00")
        assert "당일주도주 — KOSPI" in section

    def test_contains_all_stocks(self):
        from utils.report_generator import generate_market_section
        section = generate_market_section("KOSPI", _sample_data(), "11:00")
        assert "삼성전자" in section
        assert "SK하이닉스" in section
        assert "NAVER" in section

    def test_streak_label_3days(self):
        from utils.report_generator import generate_market_section
        section = generate_market_section("KOSPI", _sample_data(), "11:00")
        assert "3일 🔥" in section

    def test_streak_label_2days(self):
        from utils.report_generator import generate_market_section
        section = generate_market_section("KOSPI", _sample_data(), "11:00")
        assert "2일 ⚡" in section

    def test_close_buy_candidate_marked(self):
        from utils.report_generator import generate_market_section
        section = generate_market_section("KOSPI", _sample_data(), "11:00")
        assert "✅" in section

    def test_highlight_section_present(self):
        from utils.report_generator import generate_market_section
        section = generate_market_section("KOSPI", _sample_data(), "11:00")
        assert "연속 등장 하이라이트" in section

    def test_close_buy_section_present(self):
        from utils.report_generator import generate_market_section
        section = generate_market_section("KOSPI", _sample_data(), "11:00")
        assert "종가매매 후보" in section

    def test_section_markers(self):
        from utils.report_generator import generate_market_section
        section = generate_market_section("KOSPI", _sample_data(), "11:00")
        assert "<!-- SECTION:KOSPI -->" in section
        assert "<!-- /SECTION:KOSPI -->" in section


class TestAppendToDailyReport:

    def test_creates_new_file(self, tmp_reports):
        from utils.report_generator import append_to_daily_report, _report_path
        path = append_to_daily_report("KOSPI", _sample_data())
        assert os.path.exists(path)
        assert path.endswith(".html")

    def test_file_has_title(self, tmp_reports):
        from utils.report_generator import append_to_daily_report
        path = append_to_daily_report("KOSPI", _sample_data())
        content = open(path, encoding="utf-8").read()
        assert "Daily Report" in content

    def test_append_two_markets(self, tmp_reports):
        from utils.report_generator import append_to_daily_report
        append_to_daily_report("KOSPI", _sample_data("KOSPI"))
        path = append_to_daily_report("KOSDAQ", _sample_data("KOSDAQ"))
        content = open(path, encoding="utf-8").read()
        assert "당일주도주 — KOSPI" in content
        assert "당일주도주 — KOSDAQ" in content

    def test_replace_existing_section(self, tmp_reports):
        from utils.report_generator import append_to_daily_report
        path = append_to_daily_report("KOSPI", _sample_data())
        new_data = _sample_data()
        new_data[0]["name"] = "삼성전자_업데이트"
        append_to_daily_report("KOSPI", new_data)
        content = open(path, encoding="utf-8").read()
        assert "삼성전자_업데이트" in content
        assert content.count("당일주도주 — KOSPI") == 1

    def test_existing_html_section_preserved(self, tmp_reports):
        """다른 마켓 섹션이 있는 HTML 파일에 추가 시 기존 섹션 유지."""
        from utils.report_generator import append_to_daily_report
        append_to_daily_report("KOSPI", _sample_data("KOSPI"))
        path = append_to_daily_report("KOSDAQ", _sample_data("KOSDAQ"))
        content = open(path, encoding="utf-8").read()
        assert "당일주도주 — KOSPI" in content
        assert "당일주도주 — KOSDAQ" in content
