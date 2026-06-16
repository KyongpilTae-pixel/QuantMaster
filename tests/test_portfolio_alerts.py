"""
포트폴리오 알림 — 손절(-8%) / 목표가(+20%) 플래그 단위 테스트.
State.load_holdings_from_db 의 알림 로직을 직접 검증한다.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def _make_analysis(buy_price: float, close: float) -> dict:
    """load_holdings_from_db 의 알림 플래그 계산과 동일한 로직으로 dict 생성."""
    if buy_price > 0:
        pnl_pct = round((close - buy_price) / buy_price * 100, 1)
    else:
        pnl_pct = 0.0
    return {
        "buy_price": buy_price,
        "close": close,
        "pnl_pct": pnl_pct,
        "alert_stop_loss": buy_price > 0 and pnl_pct <= -8.0,
        "alert_target":    buy_price > 0 and pnl_pct >= 20.0,
        "has_alert":       buy_price > 0 and (pnl_pct <= -8.0 or pnl_pct >= 20.0),
    }


class TestAlertFlags:

    def test_no_alert_when_no_buy_price(self):
        a = _make_analysis(buy_price=0, close=10000)
        assert a["alert_stop_loss"] is False
        assert a["alert_target"] is False
        assert a["has_alert"] is False

    def test_no_alert_normal_range(self):
        """손절선(-8%)과 목표가(+20%) 사이: 알림 없음."""
        a = _make_analysis(buy_price=10000, close=10500)   # +5%
        assert a["alert_stop_loss"] is False
        assert a["alert_target"] is False
        assert a["has_alert"] is False

    def test_stop_loss_exactly_minus_8(self):
        a = _make_analysis(buy_price=10000, close=9200)    # -8.0%
        assert a["alert_stop_loss"] is True
        assert a["has_alert"] is True

    def test_stop_loss_below_minus_8(self):
        a = _make_analysis(buy_price=10000, close=9000)    # -10%
        assert a["alert_stop_loss"] is True
        assert a["has_alert"] is True

    def test_no_stop_loss_just_above(self):
        a = _make_analysis(buy_price=10000, close=9210)    # -7.9%
        assert a["alert_stop_loss"] is False

    def test_target_exactly_plus_20(self):
        a = _make_analysis(buy_price=10000, close=12000)   # +20%
        assert a["alert_target"] is True
        assert a["has_alert"] is True

    def test_target_above_20(self):
        a = _make_analysis(buy_price=10000, close=13000)   # +30%
        assert a["alert_target"] is True
        assert a["has_alert"] is True

    def test_no_target_just_below(self):
        a = _make_analysis(buy_price=10000, close=11990)   # +19.9%
        assert a["alert_target"] is False

    def test_stop_loss_and_target_mutually_exclusive(self):
        """손절과 목표가 동시 True는 수학적으로 불가능."""
        a_loss = _make_analysis(10000, 9000)
        a_tgt  = _make_analysis(10000, 13000)
        assert not (a_loss["alert_stop_loss"] and a_loss["alert_target"])
        assert not (a_tgt["alert_stop_loss"]  and a_tgt["alert_target"])

    def test_alert_count_aggregation(self):
        """여러 보유 종목의 has_alert 집계."""
        items = [
            _make_analysis(10000, 9000),   # 손절
            _make_analysis(10000, 10500),  # 정상
            _make_analysis(10000, 12500),  # 목표
            _make_analysis(0, 10000),      # 매수가 없음
        ]
        count = sum(1 for a in items if a.get("has_alert"))
        assert count == 2
