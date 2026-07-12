"""
QuantMaster Pro v2.0 — Reflex UI
Hybrid Quant & Technical Breakout Scanner
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import math
import logging
from datetime import datetime as _now
from typing import List

_log = logging.getLogger("leaders_debug")
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(message)s")


def _dbg(msg: str):
    """콘솔에 타임스탬프와 함께 디버그 메시지 출력."""
    line = f"[DBG {_now.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}\n"
    sys.stdout.buffer.write(line.encode("utf-8", errors="replace"))
    sys.stdout.flush()

import reflex as rx
from pydantic import BaseModel

from scanner import QuantScanner
from backtester import Backtester
from utils.reasoning import InvestmentReasoning


# ---------------------------------------------------------------------------
# Data Models (pydantic BaseModel for Reflex 0.8+)
# ---------------------------------------------------------------------------


class ScanResult(BaseModel):
    name: str = ""
    symbol: str = ""
    market_raw: str = "KOSPI"
    pbr: float = 0.0
    psr: float = 0.0
    mfi: float = 0.0
    obv_ok: bool = True
    vwap_price: float = 0.0
    close: float = 0.0
    vwap_gap: float = 0.0
    condition: str = ""
    # 적용된 임계값
    applied_pbr: float = 1.2
    applied_gpa: float = 0.6
    applied_mfi: int = 50
    applied_obv: bool = True
    applied_min_cap: str = "전체"
    currency: str = "KRW"
    market_cap_str: str = "-"
    div_yield: str = "-"


class BuyPlanStep(BaseModel):
    level: str = ""
    price: float = 0.0
    weight_pct: float = 0.0
    amount: float = 0.0
    shares: float = 0.0


class BacktestSummary(BaseModel):
    total_return: float = 0.0
    mdd: float = 0.0
    win_rate: float = 0.0
    avg_return: float = 0.0
    sharpe: float = 0.0
    trade_count: int = 0


class SavedRun(BaseModel):
    run_id: str = ""
    label: str = ""


class WhaleScanResult(BaseModel):
    name: str = ""
    symbol: str = ""
    market: str = "KOSPI"
    signal_date: str = ""
    score: int = 0
    signal_type: str = ""
    obv_spike: bool = False
    breakout: bool = False
    alpha: bool = False
    short_cover: bool = False
    close: float = 0.0
    volume_ratio: float = 0.0
    applied_step: str = "원본"


class HoldingItem(BaseModel):
    holding_id: int = 0
    name: str = ""
    symbol: str = ""
    market: str = "KOSPI"
    currency: str = "KRW"
    market_cap_str: str = "-"
    pbr: float = 0.0
    psr: float = 0.0
    div_yield: str = "-"
    mfi: float = 0.0
    close: float = 0.0
    vwap_price: float = 0.0
    vwap_gap: float = 0.0
    condition_text: str = ""
    buy_price: float = 0.0
    quantity: float = 0.0
    memo: str = ""
    added_at: str = ""


# ---------------------------------------------------------------------------
# App State
# ---------------------------------------------------------------------------


class State(rx.State):
    # Settings
    pbr_limit: List[float] = [1.2]
    vwap_period: str = "120"
    market: str = "KOSPI"
    min_cap_label: str = "전체"

    # Scanner results
    scan_results: List[ScanResult] = []
    selected_name: str = ""
    selected_symbol: str = ""
    selected_market: str = "KOSPI"
    selected_currency: str = "KRW"
    selected_market_cap_str: str = "-"
    selected_pbr: float = 0.0
    selected_psr: float = 0.0
    selected_div_yield: str = "-"
    selected_mfi: float = 0.0
    selected_close: float = 0.0
    selected_vwap_price: float = 0.0
    selected_vwap_gap: float = 0.0
    selected_condition: str = ""
    selected_holding_buy_price: float = 0.0
    selected_holding_quantity: float = 0.0
    selected_holding_memo: str = ""
    selected_is_holding: bool = False
    buy_msg: str = ""
    sell_msg: str = ""

    # Backtest results
    bt_summary: BacktestSummary = BacktestSummary()
    equity_data: List[dict] = []
    trades_data: List[dict] = []
    bt_price_chart_data: List[dict] = []
    bt_buy_points: List[dict] = []   # [{"date": "2024-01-15", "가격": 50000}, ...]
    bt_sell_points: List[dict] = []

    # 분석 차트 데이터 (종가 + VWAP)
    price_chart_data: List[dict] = []
    psr_chart_data: List[dict] = []
    close_date: str = ""
    is_loading_chart: bool = False

    # 분할 매수 플랜
    budget_input: str = "10000000"
    buy_plan_steps: List[BuyPlanStep] = []
    plan_type: str = ""
    plan_avg_price: float = 0.0
    plan_stop_loss: float = 0.0
    plan_stop_loss_pct: float = 0.0

    # 히스토리 (저장된 스캔)
    saved_runs: List[SavedRun] = []
    selected_run_id: str = ""
    selected_run_mode: str = "quant"        # 선택된 히스토리 항목의 scan_mode
    history_results: List[ScanResult] = []
    history_whale_results: List[WhaleScanResult] = []

    # 세력 탐지 스캔
    scan_mode: str = "quant"          # "quant" | "whale"
    use_alpha: bool = True
    use_short_filter: bool = True
    whale_results: List[WhaleScanResult] = []
    whale_max_minutes: int = 5        # 최대 탐색 시간 (분)
    whale_progress: str = ""          # 실시간 진행률 텍스트
    whale_stop_requested: bool = False  # 사용자 중단 요청 플래그
    scan_stop_requested: bool = False   # 비-whale 스캔 중단 요청 플래그

    # 하락장 방어 스캔
    defensive_results: List[dict] = []
    defensive_period: int = 60           # 분석 기간 (일)
    defensive_max_beta: List[float] = [0.8]  # slider → List[float]
    defensive_min_mktcap: int = 10_000   # 최소 시가총액 (억원)

    # 눌림목 스캔
    pullback_results: List[dict] = []
    pullback_min_dip: List[float] = [-5.0]   # 1W 낙폭 하한 (이 값 이하여야 통과)
    pullback_max_rsi: List[float] = [45.0]   # RSI14 상한
    pullback_min_mktcap: int = 3_000         # 최소 시가총액 (억원)

    # 추세추종 스캔
    trend_results: List[dict] = []
    trend_filter_mode: str = "relative"      # "relative"|"absolute"|"both"
    trend_progress: str = ""
    trend_min_mktcap: int = 3_000
    # 추세추종 상세 백테스트
    trend_detail_code: str = ""
    trend_detail_name: str = ""
    trend_detail_entry_label: str = ""
    trend_detail_rows: List[dict] = []
    trend_detail_loading: bool = False
    # 추세추종 계절성 분석
    season_code: str = ""
    season_entry_type: str = ""
    season_ma_period: int = 20
    season_entry_label: str = ""
    season_hold_days: int = 20
    season_rows: List[dict] = []
    season_loading: bool = False

    # 리포트 탭
    report_files: List[dict] = []            # [{date_str, filename, size_kb, filepath}]
    report_generating: bool = False
    report_status: str = ""

    # 성과 추적 탭
    tracker_picks: List[dict] = []
    tracker_summary: dict = {}
    tracker_filter_mode: str = "all"         # "all" | "quant" | "pullback" | "whale"
    tracker_filter_market: str = "all"       # "all" | "KOSPI" | "KOSDAQ" | "SP500"
    tracker_updating: bool = False
    tracker_status: str = ""

    # 세력 탐지 분석 차트 데이터
    whale_chart_data: List[dict] = []      # date, OBV, Short_Balance
    whale_highlights: List[dict] = []      # [{x1, x2}] 매집 구간 음영

    # 보유 종목
    holdings: List[HoldingItem] = []
    show_add_holding_form: bool = False
    holding_buy_price_input: str = ""
    holding_quantity_input: str = ""
    holding_memo_input: str = ""
    holding_status: str = ""               # "" | "added" | "already" | "error"

    # 보유종목분석 집계
    portfolio_count: int = 0
    portfolio_total_investment: float = 0.0
    portfolio_total_pnl: float = 0.0
    portfolio_pnl_pct: float = 0.0
    portfolio_alert_count: int = 0         # 손절/목표가 알림 종목 수
    holdings_analysis: List[dict] = []    # [{name, symbol, investment, pnl, pnl_pct, ...}]

    # 종목 조회
    lookup_query: str = ""
    lookup_market: str = "KR"
    lookup_loading: bool = False
    lookup_error: str = ""
    lookup_has_result: bool = False
    lookup_name: str = ""
    lookup_symbol: str = ""
    lookup_price: str = ""
    lookup_change_pct: str = ""
    lookup_change_positive: bool = False
    lookup_market_cap: str = "-"
    lookup_div_yield: str = "-"
    lookup_pbr: str = "-"
    lookup_per: str = "-"
    lookup_roe: str = "-"
    lookup_psr: str = "-"
    lookup_vwap: str = "-"
    lookup_mfi: str = "-"
    lookup_chart_data: List[dict] = []
    lookup_buy_score_str: str = ""
    lookup_buy_opinion: str = ""
    lookup_buy_opinion_color: str = "gray"
    lookup_buy_score_items: List[dict] = []
    lookup_is_etf: bool = False
    lookup_etf_components: List[dict] = []
    lookup_etf_base_index: str = ""
    lookup_etf_nav: str = ""
    lookup_etf_fee: str = ""
    lookup_etf_issuer: str = ""

    # 글로벌 모멘텀 전략
    momentum_rows: List[dict] = []
    momentum_loading: bool = False
    momentum_error: str = ""
    # 단순 모멘텀 추천
    momentum_recommendation: str = ""   # 하위 호환
    momentum_rec_key: str = ""
    momentum_rec_reason: str = ""
    # VAA 추천
    momentum_vaa_rec_name: str = ""
    momentum_vaa_rec_key: str = ""
    momentum_vaa_rec_desc: str = ""
    # MA200 추천
    momentum_ma_rec_name: str = ""
    momentum_ma_rec_key: str = ""
    momentum_ma_rec_desc: str = ""
    # 역변동성 배분
    momentum_invvol_rec_desc: str = ""
    momentum_invvol_rec_key: str = ""
    # 상세 테이블 전략 선택
    momentum_detail: str = "momentum"   # "momentum"|"vaa"|"ma"|"invvol"
    # 기간 토글
    momentum_show_1m: bool = True
    momentum_show_3m: bool = True
    momentum_show_6m: bool = True
    momentum_show_12m: bool = True
    # 백테스트
    momentum_bt_years: int = 10
    momentum_bt_loading: bool = False
    momentum_bt_chart: List[dict] = []
    momentum_bt_summary: List[dict] = []
    momentum_bt_error: str = ""

    # 당일 주도주
    leaders_market: str = "KOSPI"
    leaders_sort: str = "방법A"         # "방법A" | "방법B" | "거래량" | "상승률"
    leaders_type_filter: str = "전체"   # "전체" | "ETF" | "일반주"
    leaders_close_buy: bool = False     # 종가매매 후보 필터
    leaders_loading: bool = False
    leaders_b_loading: bool = False
    leaders_score_b_done: bool = False  # B점수 계산 완료 여부
    leaders_data: List[dict] = []
    leaders_data_raw: List[dict] = []  # 정렬 전 원본
    leaders_error: str = ""
    leaders_from_cache: bool = False   # 오늘 캐시에서 로드된 경우 True
    leaders_cache_time: str = ""       # 캐시 저장 시각 표시용
    leaders_data_date: str = ""        # 데이터 기준일 (YYYY-MM-DD (요))
    leaders_data_is_prev: bool = False # 오늘 날짜와 다른 전일 데이터이면 True
    # Best Pick (일반주 score_a 최고) — List[dict] 패턴 (len 0 or 1)
    leaders_best_pick: List[dict] = []

    # 섹터 모멘텀
    sector_data: List[dict] = []
    sector_loading: bool = False
    sector_error: str = ""
    sector_region: str = "KR"
    sector_sort_period: str = "1m"   # "5d"|"1m"|"3m"|"6m"|"12m"

    # 종목 모멘텀 스캔 (scanner 탭)
    stock_momentum_results: List[dict] = []
    stock_momentum_period: str = "1M"      # "1W" | "1M" | "2M" | "3M"
    stock_momentum_mktcap: int = 3_000     # 억원

    # 당일주도주 기간 확장
    leaders_period: str = "1D"            # "1D" | "1W" | "1M" | "2M" | "3M"
    leaders_multi_results: List[dict] = []
    leaders_scan_progress: str = ""       # 기간 모멘텀 스캔 진행 메시지
    leaders_prefetch_status: str = ""     # 백그라운드 캐싱 진행 메시지
    leaders_cached_markets: List[str] = []  # 오늘 캐시가 준비된 시장 목록

    # 기간 모멘텀 전용 탭
    pmom_market: str = "KOSPI"
    pmom_period: str = "3M"          # 현재 정렬 기준 기간
    pmom_results: List[dict] = []
    pmom_loading: bool = False
    pmom_error: str = ""
    pmom_scan_progress: str = ""
    pmom_from_cache: bool = False
    pmom_cache_time: str = ""
    # col1~col4 헤더 라벨 (apply_sort_and_cols 결과 — 기본 3M 정렬 순서)
    pmom_col_labels: List[str] = ["3M수익률", "1주수익률", "1M수익률", "2M수익률"]

    # UI state
    is_scanning: bool = False
    is_backtesting: bool = False
    status_msg: str = ""
    scan_warning: str = ""   # 스캔 중 데이터 수신 문제 발생 시 경고 메시지
    active_tab: str = "momentum"

    # ------------------------------------------------------------------
    # Computed vars
    # ------------------------------------------------------------------

    @rx.var
    def has_active_tasks(self) -> bool:
        return (
            self.is_scanning
            or self.is_backtesting
            or self.leaders_loading
            or self.report_generating
            or bool(self.leaders_prefetch_status)
        )

    # ------------------------------------------------------------------
    # Setters (explicit — required in Reflex 0.8+)
    # ------------------------------------------------------------------

    def set_market(self, value: str):
        _dbg(f"set_market CALLED  v={value!r}  current={self.market!r}")
        self.market = value

    def set_vwap_period(self, value: str):
        self.vwap_period = value

    def set_pbr_limit(self, values: list):
        if values:
            self.pbr_limit = [round(float(values[0]), 1)]

    def set_min_cap_label(self, value: str):
        self.min_cap_label = value

    def set_budget_input(self, value: str):
        self.budget_input = value

    def set_scan_mode(self, value: str):
        _dbg(f"set_scan_mode CALLED  v={value!r}  current={self.scan_mode!r}")
        self.scan_mode = value
        self.status_msg = ""

    def set_use_alpha(self, checked: bool):
        self.use_alpha = checked

    def set_use_short_filter(self, checked: bool):
        self.use_short_filter = checked

    def set_whale_max_minutes(self, value: str):
        try:
            v = int(value)
            if 1 <= v <= 30:
                self.whale_max_minutes = v
        except (ValueError, TypeError):
            pass

    def set_defensive_period(self, value: int):
        self.defensive_period = value

    def set_defensive_max_beta(self, values: list):
        if values:
            self.defensive_max_beta = [round(float(values[0]), 1)]

    def set_defensive_min_mktcap(self, value: int):
        self.defensive_min_mktcap = value

    def set_trend_filter_mode(self, value: str):
        if value == self.trend_filter_mode:
            return
        self.trend_filter_mode = value

    def set_trend_min_mktcap(self, value: int):
        self.trend_min_mktcap = value

    def set_holding_buy_price_input(self, value: str):
        self.holding_buy_price_input = value

    def set_holding_quantity_input(self, value: str):
        self.holding_quantity_input = value

    def set_holding_memo_input(self, value: str):
        self.holding_memo_input = value

    def toggle_add_holding_form(self):
        self.show_add_holding_form = not self.show_add_holding_form
        self.holding_buy_price_input = ""
        self.holding_quantity_input = ""
        self.holding_memo_input = ""
        self.holding_status = ""

    def add_to_holdings(self):
        if not self.selected_name or not self.selected_symbol:
            self.holding_status = "error"
            return

        from utils.scan_db import add_holding, is_holding
        already = is_holding(self.selected_symbol)
        if already:
            self.holding_status = "already"
            return

        buy_price = 0.0
        try:
            if self.holding_buy_price_input.strip():
                buy_price = float(self.holding_buy_price_input.replace(",", ""))
        except Exception:
            pass
        quantity = 0.0
        try:
            if self.holding_quantity_input.strip():
                quantity = float(self.holding_quantity_input.replace(",", ""))
        except Exception:
            pass

        try:
            add_holding(
                name=self.selected_name,
                symbol=self.selected_symbol,
                market=self.selected_market,
                currency=self.selected_currency,
                market_cap_str=self.selected_market_cap_str,
                pbr=self.selected_pbr,
                psr=self.selected_psr,
                div_yield=self.selected_div_yield,
                mfi=self.selected_mfi,
                close=self.selected_close,
                vwap_price=self.selected_vwap_price,
                vwap_gap=self.selected_vwap_gap,
                condition_text=self.selected_condition,
                buy_price=buy_price,
                quantity=quantity,
                memo=self.holding_memo_input,
            )
        except Exception as e:
            self.holding_status = f"오류: {e}"
            return
        self.holding_buy_price_input = ""
        self.holding_quantity_input = ""
        self.holding_memo_input = ""
        self.holding_status = "added"
        self.load_holdings_from_db()

    def remove_holding(self, holding_id: int):
        from utils.scan_db import remove_holding as db_remove
        db_remove(holding_id)
        self.load_holdings_from_db()

    async def select_holding_for_analysis(self, holding_id: int):
        holding = next((h for h in self.holdings if h.holding_id == holding_id), None)
        if not holding:
            return
        buy, sell = InvestmentReasoning.generate_report(
            holding.name, holding.pbr, int(self.vwap_period),
            holding.mfi, holding.vwap_price, holding.currency,
        )
        self.buy_msg = buy
        self.sell_msg = sell
        self.selected_name = holding.name
        self.selected_symbol = holding.symbol
        self.selected_market = holding.market
        self.selected_currency = holding.currency
        self.selected_market_cap_str = holding.market_cap_str
        self.selected_pbr = holding.pbr
        self.selected_psr = holding.psr
        self.selected_div_yield = holding.div_yield
        self.selected_mfi = holding.mfi
        self.selected_close = holding.close
        self.selected_vwap_price = holding.vwap_price
        self.selected_vwap_gap = holding.vwap_gap
        self.selected_condition = holding.condition_text
        self.selected_holding_buy_price = holding.buy_price
        self.selected_holding_quantity = holding.quantity
        self.selected_holding_memo = holding.memo
        self.selected_is_holding = True
        self.scan_mode = "quant"
        self.bt_summary = BacktestSummary()
        self.equity_data = []
        self.trades_data = []
        self.bt_price_chart_data = []
        self.bt_buy_points = []
        self.bt_sell_points = []
        self.price_chart_data = []
        self.psr_chart_data = []
        self.close_date = ""
        self.whale_chart_data = []
        self.whale_highlights = []
        self.is_loading_chart = True
        self.active_tab = "analysis"
        yield
        try:
            import pandas as pd
            from utils.data_loader import QuantDataLoader
            from utils.indicators import TechnicalIndicators
            vwap = int(self.vwap_period)
            loader = QuantDataLoader()
            _t1 = asyncio.create_task(asyncio.to_thread(loader.get_ohlcv, holding.symbol, 600))
            while not _t1.done():
                try:
                    df = await asyncio.wait_for(asyncio.shield(_t1), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                df = _t1.result()
            df = TechnicalIndicators.calculate_all(df, [vwap, 20, 60, 120])
            display_df = df.tail(200)
            vwap_col = f"VWAP_{vwap}"

            def _v(val):
                return round(float(val), 0) if not pd.isna(val) else None

            self.price_chart_data = [
                {
                    "date": str(d.date()),
                    "종가": _v(row["Close"]),
                    "VWAP": _v(row[vwap_col]),
                    "MA20": _v(row["TWAP_20"]),
                    "MA60": _v(row["TWAP_60"]),
                    "MA120": _v(row["TWAP_120"]),
                    "SMA120": _v(row["SMA_120"]),
                }
                for d, row in display_df.iterrows()
            ]
            self.close_date = str(display_df.index[-1].date())
            _t2 = asyncio.create_task(asyncio.to_thread(
                loader.get_quarterly_psr, holding.symbol, holding.market
            ))
            while not _t2.done():
                try:
                    psr_data = await asyncio.wait_for(asyncio.shield(_t2), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                psr_data = _t2.result()
            self.psr_chart_data = psr_data
        except Exception:
            pass
        finally:
            self.is_loading_chart = False
        yield

    def load_holdings_from_db(self):
        from utils.scan_db import load_holdings
        rows = load_holdings()
        self.holdings = [HoldingItem(**r) for r in rows]

        total_investment = 0.0
        total_pnl = 0.0
        analysis = []
        for h in self.holdings:
            investment = 0.0
            pnl = 0.0
            pnl_pct = 0.0
            if h.buy_price > 0 and h.quantity > 0:
                investment = round(h.buy_price * h.quantity, 0)
                pnl = round((h.close - h.buy_price) * h.quantity, 0)
                pnl_pct = round((h.close - h.buy_price) / h.buy_price * 100, 1)
                total_investment += investment
                total_pnl += pnl
            analysis.append({
                "holding_id": h.holding_id,
                "name": h.name,
                "symbol": h.symbol,
                "market": h.market,
                "is_us": h.market in ("SP500", "NASDAQ", "US-ETF"),
                "buy_price": h.buy_price,
                "close": h.close,
                "quantity": h.quantity,
                "investment": investment,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "mfi": h.mfi,
                "vwap_gap": h.vwap_gap,
                "memo": h.memo,
                "has_buy": h.buy_price > 0,
                "has_quantity": h.quantity > 0,
                "has_investment": investment > 0,
                "pnl_positive": pnl >= 0,
                "pct_positive": pnl_pct >= 0,
                "has_memo": bool(h.memo),
                # ── 알림 플래그 ───────────────────────────
                "alert_stop_loss": h.buy_price > 0 and pnl_pct <= -8.0,
                "alert_target":    h.buy_price > 0 and pnl_pct >= 20.0,
                "has_alert":       h.buy_price > 0 and (pnl_pct <= -8.0 or pnl_pct >= 20.0),
            })
        self.holdings_analysis = analysis
        self.portfolio_alert_count = sum(1 for a in analysis if a.get("has_alert"))
        self.portfolio_count = len(rows)
        self.portfolio_total_investment = round(total_investment, 0)
        self.portfolio_total_pnl = round(total_pnl, 0)
        self.portfolio_pnl_pct = (
            round(total_pnl / total_investment * 100, 1) if total_investment > 0 else 0.0
        )

    def load_leaders_from_cache_on_init(self):
        """서버 재시작 시 오늘 캐시가 있으면 자동 복구한다."""
        import os
        from datetime import datetime as _dt
        from utils.data_loader import load_leaders_cache, _cache_path

        data = load_leaders_cache(self.leaders_market)
        if not data:
            return

        self.leaders_data_raw = data
        self._apply_filter_and_sort()

        today_prefix = _dt.today().strftime("%Y-%m-%d")
        date_str = data[0].get("data_date", "") if data else ""
        self.leaders_data_date = date_str
        self.leaders_data_is_prev = bool(date_str) and not date_str.startswith(today_prefix)
        self.leaders_from_cache = True
        try:
            path = _cache_path(self.leaders_market)
            mtime = os.path.getmtime(path)
            self.leaders_cache_time = _dt.fromtimestamp(mtime).strftime("%H:%M")
        except Exception:
            self.leaders_cache_time = ""
        # 기간 모멘텀 캐시 현황 갱신
        self._refresh_momentum_cache_status()

    def _refresh_momentum_cache_status(self):
        """오늘 기간 모멘텀 캐시가 있는 시장 목록을 상태에 반영한다."""
        from utils.stock_scanner import load_momentum_cache_all
        self.leaders_cached_markets = [
            m for m in ("KOSPI", "KOSDAQ", "SP500")
            if load_momentum_cache_all(m)
        ]

    def set_sector_region(self, v: str):
        self.sector_region = v

    def set_pullback_min_dip(self, v: list):
        self.pullback_min_dip = v

    def set_pullback_max_rsi(self, v: list):
        self.pullback_max_rsi = v

    def set_pullback_min_mktcap(self, v: int):
        self.pullback_min_mktcap = v

    def _apply_sector_sort(self):
        """sector_sort_period 기준으로 sector_data 재정렬 + rank 갱신."""
        try:
            sort_key = f"ret_{self.sector_sort_period}"
            has_key  = f"ret_{self.sector_sort_period}_has_data"
            # Reflex proxy dict → plain Python dict 변환 후 정렬
            plain_rows = [dict(row) for row in self.sector_data]
            sorted_rows = sorted(
                plain_rows,
                key=lambda x: (x.get(sort_key) or 0.0) if x.get(has_key, False) else -999.0,
                reverse=True,
            )
            self.sector_data = [{**row, "rank": i + 1} for i, row in enumerate(sorted_rows)]
        except Exception as e:
            self.sector_error = f"정렬 오류: {e}"

    def set_sector_sort_period(self, v: str):
        if v == self.sector_sort_period:
            return
        self.sector_sort_period = v
        if len(self.sector_data) > 0:
            self._apply_sector_sort()

    async def fetch_sector_momentum(self):
        if self.sector_loading:
            return
        self.sector_loading = True
        self.sector_error = ""
        self.sector_data = []
        yield
        import asyncio
        from utils.sector_scanner import fetch_sector_momentum
        try:
            _t = asyncio.create_task(asyncio.to_thread(
                fetch_sector_momentum, self.sector_region
            ))
            while not _t.done():
                try:
                    data = await asyncio.wait_for(asyncio.shield(_t), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                data = _t.result()
            self.sector_data = data
            self._apply_sector_sort()
        except Exception as e:
            self.sector_error = str(e)
        finally:
            self.sector_loading = False

    async def stop_whale_scan(self):
        """탐색 중단 요청 (다음 단계 시작 전 반영)."""
        self.whale_stop_requested = True
        self.whale_progress = "종목 분석을 마무리하는 중입니다. 잠시만 기다려 주세요..."
        self.status_msg = "탐색 중단 요청됨"
        yield

    async def stop_general_scan(self):
        """퀀트/눌림목/추세추종/하락방어/모멘텀 스캔 중단 요청."""
        if not self.is_scanning:
            return
        self.scan_stop_requested = True
        self.status_msg = "스캔 중단 요청됨..."
        yield

    def set_tab(self, tab: str):
        _dbg(f"set_tab CALLED  tab={tab!r}  current={self.active_tab!r}")
        if not tab or tab == self.active_tab:
            return
        self.active_tab = tab
        if tab == "history":
            from utils.scan_db import load_run_list
            runs = load_run_list()
            self.saved_runs = [SavedRun(run_id=r["id"], label=r["label"]) for r in runs]
        elif tab == "portfolio":
            self.load_holdings_from_db()
        elif tab == "pmom":
            return State.do_load_pmom
        elif tab == "report":
            self.load_report_files()
        elif tab == "tracker":
            self.load_tracker_picks()

    def load_report_files(self):
        """quantReports/ 폴더의 HTML 파일 목록 로드."""
        import os as _os
        reports_dir = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "quantReports")
        files: list[dict] = []
        if _os.path.isdir(reports_dir):
            for fn in sorted(_os.listdir(reports_dir), reverse=True):
                if fn.endswith(".html"):
                    fp = _os.path.join(reports_dir, fn)
                    size_kb = round(_os.path.getsize(fp) / 1024, 1)
                    files.append({
                        "date_str": fn[:-5],
                        "filename": fn,
                        "size_kb": str(size_kb),
                        "filepath": fp,
                    })
        self.report_files = files

    def open_report_file(self, filepath: str):
        """OS 기본 브라우저로 리포트 HTML 파일 열기 (os.startfile)."""
        import os as _os
        if filepath and _os.path.exists(filepath):
            _os.startfile(filepath)

    @rx.event(background=True)
    async def generate_daily_report_event(self):
        import asyncio
        async with self:
            self.report_generating = True
            self.report_status = "일별 리포트 생성 중... (약 30~60초 소요)"
        try:
            from utils.report_generator import generate_full_daily_report
            path = await asyncio.to_thread(generate_full_daily_report)
            async with self:
                self.report_status = f"완료 → {path}"
        except Exception as e:
            async with self:
                self.report_status = f"오류: {e}"
        finally:
            async with self:
                self.report_generating = False
                self.load_report_files()

    @rx.event(background=True)
    async def generate_weekly_report_event(self):
        import asyncio
        async with self:
            self.report_generating = True
            self.report_status = "주간 리포트 생성 중... (약 30~60초 소요)"
        try:
            from utils.weekly_report_generator import generate_full_weekly_report
            path = await asyncio.to_thread(generate_full_weekly_report)
            async with self:
                self.report_status = f"완료 → {path}"
        except Exception as e:
            async with self:
                self.report_status = f"오류: {e}"
        finally:
            async with self:
                self.report_generating = False
                self.load_report_files()

    def load_tracker_picks(self):
        """성과 추적 종목 로드 (필터 적용)."""
        from utils.scan_results_tracker import load_tracked_picks, get_tracker_summary
        mode   = None if self.tracker_filter_mode   == "all" else self.tracker_filter_mode
        market = None if self.tracker_filter_market == "all" else self.tracker_filter_market
        picks  = load_tracked_picks(days=30, scan_mode=mode, market=market)
        self.tracker_picks   = picks
        self.tracker_summary = get_tracker_summary(picks)

    def set_tracker_filter_mode(self, v: str):
        if v == self.tracker_filter_mode:
            return
        self.tracker_filter_mode = v
        self.load_tracker_picks()

    def set_tracker_filter_market(self, v: str):
        if v == self.tracker_filter_market:
            return
        self.tracker_filter_market = v
        self.load_tracker_picks()

    async def update_tracker_prices(self):
        """활성 종목 현재가 일괄 업데이트."""
        self.tracker_updating = True
        self.tracker_status   = "현재가 업데이트 중..."
        yield
        import asyncio
        try:
            from utils.scan_results_tracker import update_pick_prices
            _t = asyncio.create_task(asyncio.to_thread(update_pick_prices))
            while not _t.done():
                try:
                    n = await asyncio.wait_for(asyncio.shield(_t), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                n = _t.result()
            self.tracker_status = f"완료 — {n}건 업데이트"
        except Exception as e:
            self.tracker_status = f"오류: {e}"
        finally:
            self.tracker_updating = False
        self.load_tracker_picks()

    async def run_auto_scan_now(self):
        """퀀트+눌림목 스캔 즉시 실행 → tracked_picks 저장."""
        self.tracker_updating = True
        self.tracker_status   = "스캔 실행 중... (3~5분 소요)"
        yield
        import asyncio
        try:
            from utils.scan_results_tracker import save_scan_picks
            from utils.pullback_scanner import scan_pullback_stocks
            from scanner import QuantScanner
            total = 0
            for mkt in ("KOSPI", "KOSDAQ", "SP500"):
                # 퀀트
                try:
                    _tq = asyncio.create_task(asyncio.to_thread(lambda m=mkt: QuantScanner(market=m).scan()))
                    while not _tq.done():
                        try:
                            r = await asyncio.wait_for(asyncio.shield(_tq), timeout=0.5)
                            break
                        except asyncio.TimeoutError:
                            yield
                    else:
                        r = _tq.result()
                    if r:
                        total += save_scan_picks("quant", mkt, list(r))
                except Exception:
                    pass
                # 눌림목
                try:
                    _tp = asyncio.create_task(asyncio.to_thread(
                        scan_pullback_stocks, mkt,
                        3_000 if mkt != "SP500" else 0,
                        -5.0, 45.0, 0.0, 30, 150, 90,
                    ))
                    while not _tp.done():
                        try:
                            r2 = await asyncio.wait_for(asyncio.shield(_tp), timeout=0.5)
                            break
                        except asyncio.TimeoutError:
                            yield
                    else:
                        r2 = _tp.result()
                    if r2:
                        total += save_scan_picks("pullback", mkt, list(r2))
                except Exception:
                    pass
            self.tracker_status = f"스캔 완료 — {total}건 신규 저장"
        except Exception as e:
            self.tracker_status = f"오류: {e}"
        finally:
            self.tracker_updating = False
        self.load_tracker_picks()

    def toggle_momentum_1m(self):
        self.momentum_show_1m = not self.momentum_show_1m

    def toggle_momentum_3m(self):
        self.momentum_show_3m = not self.momentum_show_3m

    def toggle_momentum_6m(self):
        self.momentum_show_6m = not self.momentum_show_6m

    def toggle_momentum_12m(self):
        self.momentum_show_12m = not self.momentum_show_12m

    def set_momentum_detail(self, v: str):
        self.momentum_detail = v

    def set_momentum_bt_years(self, v: int):
        self.momentum_bt_years = v

    async def fetch_momentum(self):
        from utils.momentum_scanner import fetch_momentum_data
        self.momentum_loading = True
        self.momentum_error = ""
        self.momentum_rows = []
        self.momentum_recommendation = ""
        yield
        try:
            _t = asyncio.create_task(asyncio.to_thread(fetch_momentum_data))
            while not _t.done():
                try:
                    r = await asyncio.wait_for(asyncio.shield(_t), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                r = _t.result()
            self.momentum_rows = r["rows"]
            # 단순 모멘텀
            self.momentum_recommendation = r["momentum_rec_name"]
            self.momentum_rec_key = r["momentum_rec_key"]
            self.momentum_rec_reason = r["momentum_rec_desc"]
            # VAA
            self.momentum_vaa_rec_name = r["vaa_rec_name"]
            self.momentum_vaa_rec_key = r["vaa_rec_key"]
            self.momentum_vaa_rec_desc = r["vaa_rec_desc"]
            # MA200
            self.momentum_ma_rec_name = r["ma_rec_name"]
            self.momentum_ma_rec_key = r["ma_rec_key"]
            self.momentum_ma_rec_desc = r["ma_rec_desc"]
            # 역변동성
            self.momentum_invvol_rec_desc = r["invvol_rec_desc"]
            self.momentum_invvol_rec_key = r["invvol_rec_key"]
        except Exception as e:
            self.momentum_error = f"오류: {e}"
        finally:
            self.momentum_loading = False
        yield

    async def run_momentum_backtest(self):
        from utils.momentum_backtest import run_backtest
        self.momentum_bt_loading = True
        self.momentum_bt_error = ""
        self.momentum_bt_chart = []
        self.momentum_bt_summary = []
        yield
        try:
            _t = asyncio.create_task(asyncio.to_thread(run_backtest, self.momentum_bt_years))
            while not _t.done():
                try:
                    r = await asyncio.wait_for(asyncio.shield(_t), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                r = _t.result()
            self.momentum_bt_chart = r["chart_data"]
            self.momentum_bt_summary = r["summary"]
            self.momentum_bt_error = r.get("error", "")
        except Exception as e:
            self.momentum_bt_error = f"오류: {e}"
        finally:
            self.momentum_bt_loading = False
        yield

    def set_leaders_market(self, v: str):
        _dbg(f"set_leaders_market CALLED  v={v!r}  current={self.leaders_market!r}")
        if v == self.leaders_market:
            _dbg("set_leaders_market SKIPPED (same value)")
            return
        self.leaders_market = v

    def set_leaders_period(self, v: str):
        _dbg(f"set_leaders_period CALLED  v={v!r}  current={self.leaders_period!r}")
        self.leaders_period = v
        self.leaders_multi_results = []
        self.leaders_data = []
        self.leaders_data_raw = []
        self.leaders_data_date = ""
        self.leaders_error = ""

    def set_stock_momentum_period(self, v: str):
        self.stock_momentum_period = v

    def set_stock_momentum_mktcap(self, v: int):
        self.stock_momentum_mktcap = v

    def _compute_best_pick(self):
        """일반주 중 score_a 최고 종목을 leaders_best_pick (len 0 or 1) 에 저장."""
        try:
            stocks = [x for x in self.leaders_data_raw if not x.get("is_etf", False)]
            if not stocks:
                self.leaders_best_pick = []
                return
            best = max(stocks, key=lambda x: x.get("score_a", 0))
            name = best.get("name", "")
            code = best.get("code", "")
            if not name and not code:
                self.leaders_best_pick = []
                return

            parts = []
            change_str = best.get("change_pct_str", "")
            vol_rank   = best.get("vol_rank_str", "")
            rise_rank  = best.get("rise_rank_str", "")
            streak     = int(best.get("consecutive_days", 1))
            near_high  = bool(best.get("is_near_high", False))
            score_a    = best.get("score_a_str", "")

            if change_str and change_str not in ("", "-"):
                parts.append(f"당일 {change_str}")
            if vol_rank and vol_rank not in ("", "-"):
                parts.append(f"거래량 {vol_rank}위")
            if rise_rank and rise_rank not in ("", "-"):
                parts.append(f"상승률 {rise_rank}위")
            if streak >= 2:
                parts.append(f"{streak}일 연속 상승")
            if near_high:
                parts.append("52주 신고가 근접")
            if score_a:
                parts.append(f"A점수 {score_a}")

            self.leaders_best_pick = [{
                "name":   name,
                "code":   code,
                "reason": " · ".join(parts) if parts else "A점수 1위 일반주",
                "is_us":  bool(best.get("is_us", False)),
            }]
        except Exception:
            self.leaders_best_pick = []

    def _apply_filter_and_sort(self):
        """leaders_data_raw에 타입 필터 + 정렬을 적용해 leaders_data 갱신."""
        key_map = {
            "방법A": lambda x: x.get("score_a", 0),
            "방법B": lambda x: x.get("score_b", 0),
            "거래량": lambda x: x.get("today_volume", 0),
            "상승률": lambda x: x.get("change_pct_val", 0),
        }
        key_fn = key_map.get(self.leaders_sort, lambda x: x.get("score_a", 0))
        filtered = [dict(item) for item in self.leaders_data_raw]
        if self.leaders_type_filter == "ETF":
            filtered = [item for item in filtered if item.get("is_etf", False)]
        elif self.leaders_type_filter == "일반주":
            filtered = [item for item in filtered if not item.get("is_etf", False)]
        if self.leaders_close_buy:
            filtered = [
                item for item in filtered
                if item.get("change_pct_val", 0) >= 5.0        # 상승률 5% 이상
                and item.get("is_near_high", False)             # 고가 근처 마감
                and item.get("has_vol_rank", False)             # 거래량 상위 등재
                and item.get("has_rise_rank", False)            # 상승률 상위 등재
            ]
        self.leaders_data = [
            {**item, "rank": i + 1}
            for i, item in enumerate(sorted(filtered, key=key_fn, reverse=True))
        ]
        self._compute_best_pick()

    def set_leaders_sort(self, v: str):
        if not self.leaders_data_raw:
            self.leaders_sort = v
            return
        if v == self.leaders_sort:
            return
        self.leaders_sort = v
        self._apply_filter_and_sort()

    def toggle_leaders_close_buy(self):
        self.leaders_close_buy = not self.leaders_close_buy
        if self.leaders_data_raw:
            self._apply_filter_and_sort()

    def set_leaders_type_filter(self, v: str):
        changed = v != self.leaders_type_filter
        self.leaders_type_filter = v
        if v == "전체":
            self.leaders_close_buy = False  # 전체 = 모든 필터 해제
        if (changed or v == "전체") and self.leaders_data_raw:
            self._apply_filter_and_sort()

    async def do_fetch_leaders(self):
        _dbg(f"do_fetch_leaders CALLED  loading={self.leaders_loading}  period={self.leaders_period}  market={self.leaders_market}")
        if self.leaders_loading:
            _dbg("do_fetch_leaders BLOCKED (already loading)")
            return
        self.leaders_loading = True
        self.leaders_error = ""
        self.leaders_data = []
        self.leaders_data_raw = []
        self.leaders_sort = "방법A"
        self.leaders_type_filter = "전체"
        self.leaders_close_buy = False
        self.leaders_score_b_done = False
        self.leaders_from_cache = False
        self.leaders_cache_time = ""
        self.leaders_data_date = ""
        self.leaders_data_is_prev = False
        self.leaders_multi_results = []
        self.leaders_best_pick = []
        _dbg(f"do_fetch_leaders YIELDING  period={self.leaders_period}  market={self.leaders_market}")
        yield
        _dbg("do_fetch_leaders RESUMED after yield - starting async fetch")

        import asyncio
        from datetime import datetime as _dt

        # ── 기간 선택 모드 (1W / 1M / 2M / 3M) — 현재 UI 미사용, pmom 탭으로 이전 ──
        if self.leaders_period != "1D":
            import threading
            from utils.stock_scanner import (
                scan_stock_momentum_all_periods,
                load_momentum_cache_all,
                save_momentum_cache_all,
                apply_sort_and_cols,
            )
            mkt    = self.leaders_market
            period = self.leaders_period

            # ── 캐시 먼저 확인 → 즉시 로드 ─────────────────────────
            cached_all = load_momentum_cache_all(mkt)
            if cached_all:
                import os as _os
                from utils.stock_scanner import _momentum_all_cache_path
                sorted_rows, _ = apply_sort_and_cols(list(cached_all), period, top_n=30)
                self.leaders_multi_results = sorted_rows
                self.leaders_data_date     = _dt.today().strftime("%Y-%m-%d")
                self.leaders_from_cache    = True
                try:
                    mtime = _os.path.getmtime(_momentum_all_cache_path(mkt))
                    self.leaders_cache_time = _dt.fromtimestamp(mtime).strftime("%H:%M")
                except Exception:
                    self.leaders_cache_time = ""
                _dbg(f"do_fetch_leaders FROM CACHE  {mkt}/{period}  results={len(sorted_rows)}")
                self.leaders_loading = False
                return

            # ── 캐시 없음: 3개월 OHLCV 1회 수집 ─────────────────────
            _prog: dict = {"current": 0, "total": 0}
            _lock = threading.Lock()

            def _on_progress(current: int, total: int):
                with _lock:
                    _prog["current"] = current
                    _prog["total"]   = total

            try:
                scan_task = asyncio.create_task(
                    asyncio.to_thread(
                        scan_stock_momentum_all_periods,
                        mkt, 1_000, 30, 150, 90, _on_progress,
                    )
                )
                while not scan_task.done():
                    try:
                        data_all_inner = await asyncio.wait_for(asyncio.shield(scan_task), timeout=0.5)
                        break
                    except asyncio.TimeoutError:
                        with _lock:
                            curr, tot = _prog["current"], _prog["total"]
                        if tot > 0:
                            self.leaders_scan_progress = f"{curr}/{tot}개 종목 처리 중..."
                        yield
                else:
                    data_all_inner = scan_task.result()

                data_all = data_all_inner
                self.leaders_scan_progress = ""

                if data_all:
                    _st = asyncio.create_task(asyncio.to_thread(save_momentum_cache_all, mkt, data_all))
                    while not _st.done():
                        try:
                            await asyncio.wait_for(asyncio.shield(_st), timeout=0.5)
                            break
                        except asyncio.TimeoutError:
                            yield
                    self._refresh_momentum_cache_status()
                    sorted_rows, _ = apply_sort_and_cols(list(data_all), period, top_n=30)
                    self.leaders_multi_results = sorted_rows
                    self.leaders_data_date     = _dt.today().strftime("%Y-%m-%d")
                    w = getattr(data_all, "warning", "")
                    if w:
                        self.leaders_error = w

                _dbg(f"do_fetch_leaders SCANNED  {mkt}  results={len(self.leaders_multi_results)}")
            except Exception as e:
                _dbg(f"do_fetch_leaders multi-period ERROR  {e}")
                self.leaders_error = str(e)
                self.leaders_scan_progress = ""
            finally:
                _dbg("do_fetch_leaders multi-period FINALLY  loading=False")
                self.leaders_loading = False
            return

        # ── 당일(1D) 모드 — 기존 로직 ────────────────────────────────────
        from utils.data_loader import fetch_leaders_combined
        _dbg(f"do_fetch_leaders 1D fetch START  market={self.leaders_market}")

        try:
            # ① 주도주 fetch (10~20초) — 3초마다 yield로 WebSocket 유지
            _t1 = asyncio.create_task(asyncio.to_thread(fetch_leaders_combined, self.leaders_market))
            while not _t1.done():
                try:
                    data = await asyncio.wait_for(asyncio.shield(_t1), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                data = _t1.result()
            _dbg(f"do_fetch_leaders fetch_leaders_combined DONE  items={len(data)}")

            # ② 연속 등장 계산 (KR 전용, 5~10초)
            if self.leaders_market in ("KOSPI", "KOSDAQ"):
                from utils.data_loader import compute_consecutive_days
                _t2 = asyncio.create_task(asyncio.to_thread(compute_consecutive_days, self.leaders_market, data))
                while not _t2.done():
                    try:
                        data = await asyncio.wait_for(asyncio.shield(_t2), timeout=0.5)
                        break
                    except asyncio.TimeoutError:
                        yield
                else:
                    data = _t2.result()
                _dbg(f"do_fetch_leaders compute_consecutive_days DONE  items={len(data)}")
            else:
                data = [{**item, "consecutive_days": 1, "has_streak": False, "streak_hot": False} for item in data]

            self.leaders_data_raw = data
            self._apply_filter_and_sort()
            _dbg(f"do_fetch_leaders _apply_filter_and_sort DONE  leaders_data={len(self.leaders_data)}")
            today_prefix = _dt.today().strftime("%Y-%m-%d")
            date_str = data[0].get("data_date", "") if data else ""
            self.leaders_data_date = date_str
            self.leaders_data_is_prev = bool(date_str) and not date_str.startswith(today_prefix)
            _dbg(f"do_fetch_leaders date={date_str!r}  is_prev={self.leaders_data_is_prev}")

            # ③ KR 당일 데이터: 캐시 저장 + 일별 리포트 갱신 (백그라운드성, 실패 무시)
            if self.leaders_market in ("KOSPI", "KOSDAQ") and not self.leaders_data_is_prev:
                _dbg("do_fetch_leaders saving cache...")
                from utils.data_loader import save_leaders_cache
                _t3 = asyncio.create_task(asyncio.to_thread(save_leaders_cache, self.leaders_market, data))
                while not _t3.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(_t3), timeout=0.5)
                        break
                    except asyncio.TimeoutError:
                        yield
                _dbg("do_fetch_leaders cache saved. appending daily report...")
                try:
                    from utils.report_generator import append_to_daily_report
                    _t4 = asyncio.create_task(asyncio.to_thread(append_to_daily_report, self.leaders_market, data))
                    while not _t4.done():
                        try:
                            await asyncio.wait_for(asyncio.shield(_t4), timeout=0.5)
                            break
                        except asyncio.TimeoutError:
                            yield
                    _dbg("do_fetch_leaders daily report done")
                except Exception as rep_e:
                    _dbg(f"do_fetch_leaders daily report ERROR (ignored)  {rep_e}")
        except Exception as e:
            _dbg(f"do_fetch_leaders EXCEPTION  {e}")
            self.leaders_error = str(e)
        finally:
            _dbg(f"do_fetch_leaders FINALLY  loading=False  data_items={len(self.leaders_data)}")
            self.leaders_loading = False
        _dbg("do_fetch_leaders FUNCTION END")

    @rx.event(background=True)
    async def do_prefetch_momentum_bg(self):
        """서버 시작 시 KOSPI/KOSDAQ 기간 모멘텀 캐시를 백그라운드로 미리 수집한다.

        @rx.background: State 락을 점유하지 않고 실행 → WebSocket 유지.
        상태 갱신은 async with self: 블록에서만 순간적으로 락 획득.
        """
        import asyncio as _aio
        from utils.stock_scanner import (
            scan_stock_momentum_all_periods,
            load_momentum_cache_all,
            save_momentum_cache_all,
        )

        markets = ["KOSPI", "KOSDAQ"]
        need = [m for m in markets if not load_momentum_cache_all(m)]
        if not need:
            async with self:
                self._refresh_momentum_cache_status()
            return

        total = len(need)
        for idx, market in enumerate(need, 1):
            async with self:
                self.leaders_prefetch_status = f"기간 데이터 캐싱 중... {market} ({idx}/{total})"
            try:
                data_all = await _aio.to_thread(
                    scan_stock_momentum_all_periods, market, 1_000, 30, 150, 90
                )
                if data_all:
                    await _aio.to_thread(save_momentum_cache_all, market, data_all)
                    async with self:
                        self._refresh_momentum_cache_status()
                    _dbg(f"do_prefetch_momentum_bg DONE  {market}")
            except Exception as e:
                _dbg(f"do_prefetch_momentum_bg ERROR  {market}  {e}")

        async with self:
            self.leaders_prefetch_status = ""

    # ------------------------------------------------------------------
    # 기간 모멘텀 탭 (pmom)
    # ------------------------------------------------------------------

    def set_pmom_market(self, v: str):
        if v == self.pmom_market:
            return
        self.pmom_market = v
        self.pmom_results = []
        self.pmom_from_cache = False
        self.pmom_error = ""
        return State.do_load_pmom

    def set_pmom_period(self, v: str):
        if v == self.pmom_period:
            return
        self.pmom_period = v
        if not self.pmom_results:
            return
        from utils.stock_scanner import apply_sort_and_cols
        sorted_rows, labels = apply_sort_and_cols(list(self.pmom_results), v, top_n=30)
        self.pmom_results = sorted_rows
        self.pmom_col_labels = labels

    async def do_load_pmom(self):
        """기간 모멘텀 탭 진입 시 캐시 즉시 로드, 없으면 스캔 실행."""
        import asyncio as _aio
        import os as _os
        import threading
        from datetime import datetime as _dt
        from utils.stock_scanner import (
            load_momentum_cache_all,
            save_momentum_cache_all,
            scan_stock_momentum_all_periods,
            _momentum_all_cache_path,
        )

        from utils.stock_scanner import apply_sort_and_cols

        # 캐시 확인 → 즉시 반환
        cached = load_momentum_cache_all(self.pmom_market)
        if cached:
            sorted_rows, labels = apply_sort_and_cols(list(cached), self.pmom_period, top_n=30)
            self.pmom_results = sorted_rows
            self.pmom_col_labels = labels
            self.pmom_from_cache = True
            try:
                mtime = _os.path.getmtime(_momentum_all_cache_path(self.pmom_market))
                self.pmom_cache_time = _dt.fromtimestamp(mtime).strftime("%H:%M")
            except Exception:
                self.pmom_cache_time = ""
            return

        # 캐시 없음 → 스캔
        if self.pmom_loading:
            return
        self.pmom_loading = True
        self.pmom_error = ""
        self.pmom_scan_progress = ""
        yield

        _prog: dict = {"current": 0, "total": 0}
        _lock = threading.Lock()

        def _on_progress(cur: int, tot: int):
            with _lock:
                _prog["current"] = cur
                _prog["total"]   = tot

        try:
            task = _aio.create_task(
                _aio.to_thread(
                    scan_stock_momentum_all_periods,
                    self.pmom_market, 1_000, 30, 150, 90, _on_progress,
                )
            )
            while not task.done():
                try:
                    data_all_inner = await _aio.wait_for(_aio.shield(task), timeout=0.5)
                    break
                except _aio.TimeoutError:
                    with _lock:
                        curr, tot = _prog["current"], _prog["total"]
                    if tot > 0:
                        self.pmom_scan_progress = f"{curr}/{tot}개 종목 처리 중..."
                    yield
            else:
                data_all_inner = task.result()

            data_all = data_all_inner
            self.pmom_scan_progress = ""
            if data_all:
                _save_task = _aio.create_task(_aio.to_thread(save_momentum_cache_all, self.pmom_market, data_all))
                while not _save_task.done():
                    try:
                        await _aio.wait_for(_aio.shield(_save_task), timeout=0.5)
                        break
                    except _aio.TimeoutError:
                        yield
                self._refresh_momentum_cache_status()
                sorted_rows, labels = apply_sort_and_cols(list(data_all), self.pmom_period, top_n=30)
                self.pmom_results = sorted_rows
                self.pmom_col_labels = labels
                self.pmom_from_cache = False
        except Exception as e:
            self.pmom_error = str(e)
            self.pmom_scan_progress = ""
        finally:
            self.pmom_loading = False

    async def do_refresh_leaders_quick(self):
        """기간 모멘텀 결과의 기존 30종목 가격만 재조회 (빠른 갱신).

        전체 유니버스를 재스캔하지 않고 이미 발굴된 종목의 수익률을 최신화한다.
        """
        _dbg(f"do_refresh_leaders_quick CALLED  loading={self.leaders_loading}  results={len(self.leaders_multi_results)}")
        if self.leaders_loading or not self.leaders_multi_results:
            return
        self.leaders_loading = True
        self.leaders_error = ""
        yield
        import asyncio
        try:
            from utils.stock_scanner import refresh_stock_momentum
            existing = [dict(r) for r in self.leaders_multi_results]
            _t = asyncio.create_task(asyncio.to_thread(
                refresh_stock_momentum, existing, self.leaders_period
            ))
            while not _t.done():
                try:
                    data = await asyncio.wait_for(asyncio.shield(_t), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                data = _t.result()
            self.leaders_multi_results = list(data)
            warn = getattr(data, "warning", "")
            if warn:
                self.leaders_error = warn
        except Exception as e:
            self.leaders_error = str(e)
        finally:
            self.leaders_loading = False

    async def do_compute_score_b(self):
        _dbg(f"do_compute_score_b CALLED  raw_items={len(self.leaders_data_raw)}")
        if not self.leaders_data_raw:
            return
        # Reflex 리액티브 래퍼를 순수 Python 객체로 변환 후 스레드에 전달
        raw_snapshot = [dict(item) for item in self.leaders_data_raw]
        self.leaders_b_loading = True
        yield

        import asyncio
        from utils.data_loader import compute_score_b

        try:
            _t = asyncio.create_task(asyncio.to_thread(compute_score_b, raw_snapshot))
            while not _t.done():
                try:
                    updated = await asyncio.wait_for(asyncio.shield(_t), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                updated = _t.result()
            self.leaders_data_raw = updated
            self._apply_filter_and_sort()
            self.leaders_score_b_done = True
        except Exception as e:
            self.leaders_error = str(e)
        finally:
            self.leaders_b_loading = False

    async def goto_lookup_from_leaders(self, code: str, is_us: bool = False):
        self.lookup_query = code
        self.lookup_market = "US" if is_us else "KR"
        self.active_tab = "lookup"
        self.lookup_has_result = False
        self.lookup_error = ""
        self.lookup_chart_data = []
        self.lookup_loading = True
        yield

        import asyncio
        from utils.data_loader import fetch_stock_info

        _t = asyncio.create_task(asyncio.to_thread(fetch_stock_info, code, self.lookup_market))
        while not _t.done():
            try:
                result = await asyncio.wait_for(asyncio.shield(_t), timeout=0.5)
                break
            except asyncio.TimeoutError:
                yield
        else:
            result = _t.result()
        self.lookup_loading = False
        if result["error"]:
            self.lookup_error = result["error"]
        else:
            price = result["price"]
            change = result["change_pct"]
            self.lookup_name = result["name"]
            self.lookup_symbol = result["symbol"]
            self.lookup_price = f"{price:,.0f}" if price >= 1 else f"{price:.4f}"
            self.lookup_change_pct = f"{change:+.2f}%"
            self.lookup_change_positive = result["change_positive"]
            self.lookup_market_cap = result["market_cap"]
            self.lookup_div_yield = result["div_yield"]
            self.lookup_pbr = result["pbr"]
            self.lookup_per = result["per"]
            self.lookup_roe = result["roe"]
            self.lookup_psr = result["psr"]
            self.lookup_vwap = result["vwap"]
            self.lookup_mfi = result["mfi"]
            self.lookup_chart_data = result.get("chart_data", [])
            self.lookup_buy_score_str = result.get("buy_score_str", "")
            self.lookup_buy_opinion = result.get("buy_opinion", "")
            self.lookup_buy_opinion_color = result.get("buy_opinion_color", "gray")
            self.lookup_buy_score_items = result.get("buy_score_items", [])
            self.lookup_is_etf = result.get("is_etf", False)
            ea = result.get("etf_analysis", {})
            self.lookup_etf_components = ea.get("components", [])
            self.lookup_etf_base_index = ea.get("base_index", "")
            self.lookup_etf_nav = ea.get("nav", "")
            self.lookup_etf_fee = ea.get("total_fee", "")
            self.lookup_etf_issuer = ea.get("issuer", "")
            self.lookup_has_result = True

    def set_lookup_query(self, v: str):
        self.lookup_query = v

    def set_lookup_market(self, v: str):
        self.lookup_market = v

    def handle_lookup_key(self, key: str):
        if key == "Enter":
            return State.do_lookup_stock()

    async def do_lookup_stock(self):
        q = self.lookup_query.strip()
        if not q:
            return
        self.lookup_loading = True
        self.lookup_has_result = False
        self.lookup_error = ""
        yield

        import asyncio
        from utils.data_loader import fetch_stock_info

        _t = asyncio.create_task(asyncio.to_thread(fetch_stock_info, q, self.lookup_market))
        while not _t.done():
            try:
                result = await asyncio.wait_for(asyncio.shield(_t), timeout=0.5)
                break
            except asyncio.TimeoutError:
                yield
        else:
            result = _t.result()

        self.lookup_loading = False
        if result["error"]:
            self.lookup_error = result["error"]
        else:
            self.lookup_name = result["name"]
            self.lookup_symbol = result["symbol"]
            price = result["price"]
            change = result["change_pct"]
            self.lookup_price = f"{price:,.0f}" if price >= 1 else f"{price:.4f}"
            self.lookup_change_pct = f"{change:+.2f}%"
            self.lookup_change_positive = result["change_positive"]
            self.lookup_market_cap = result["market_cap"]
            self.lookup_div_yield = result["div_yield"]
            self.lookup_pbr = result["pbr"]
            self.lookup_per = result["per"]
            self.lookup_roe = result["roe"]
            self.lookup_psr = result["psr"]
            self.lookup_vwap = result["vwap"]
            self.lookup_mfi = result["mfi"]
            self.lookup_chart_data = result.get("chart_data", [])
            self.lookup_buy_score_str = result.get("buy_score_str", "")
            self.lookup_buy_opinion = result.get("buy_opinion", "")
            self.lookup_buy_opinion_color = result.get("buy_opinion_color", "gray")
            self.lookup_buy_score_items = result.get("buy_score_items", [])
            self.lookup_is_etf = result.get("is_etf", False)
            ea = result.get("etf_analysis", {})
            self.lookup_etf_components = ea.get("components", [])
            self.lookup_etf_base_index = ea.get("base_index", "")
            self.lookup_etf_nav = ea.get("nav", "")
            self.lookup_etf_fee = ea.get("total_fee", "")
            self.lookup_etf_issuer = ea.get("issuer", "")
            self.lookup_has_result = True

    def set_selected_run_id(self, value: str):
        self.selected_run_id = value
        self.history_results = []
        self.history_whale_results = []
        if value:
            from utils.scan_db import get_run_mode, load_scan_results, load_whale_results
            mode = get_run_mode(int(value))
            self.selected_run_mode = mode
            if mode == "whale":
                rows = load_whale_results(int(value))
                self.history_whale_results = [WhaleScanResult(**r) for r in rows]
            else:
                rows = load_scan_results(int(value))
                self.history_results = [ScanResult(**r) for r in rows]

    def save_scan(self):
        """현재 퀀트 스캔 결과를 DB에 저장."""
        if not self.scan_results:
            return
        from utils.scan_db import save_scan as db_save
        run_id = db_save(
            market=self.market,
            vwap_period=int(self.vwap_period),
            target_pbr=self.pbr_limit[0],
            min_cap_label=self.min_cap_label,
            results=self.scan_results,
            scan_mode="quant",
        )
        self.status_msg = f"퀀트 결과 저장 완료 (#{run_id})"

    def save_whale_scan(self):
        """현재 세력 탐지 결과를 DB에 저장."""
        if not self.whale_results:
            return
        from utils.scan_db import save_whale_scan as db_save
        run_id = db_save(
            market=self.market,
            results=self.whale_results,
        )
        self.status_msg = f"세력 탐지 결과 저장 완료 (#{run_id})"

    def _find_result(self, name: str):
        """scan_results와 history_results 모두에서 종목 검색."""
        return next(
            (r for r in self.scan_results if r.name == name),
            next((r for r in self.history_results if r.name == name), None),
        )

    def _find_whale_result(self, name: str):
        """whale_results에서 종목 검색."""
        return next((r for r in self.whale_results if r.name == name), None)

    def calc_buy_plan(self):
        """예산 입력 후 분할 매수 플랜 계산."""
        target = self._find_result(self.selected_name)
        if not target:
            return
        try:
            from utils.strategy_engine import calculate_pullback_plan
            budget = float(self.budget_input.replace(",", ""))
            result = calculate_pullback_plan(
                current_price=target.close,
                vwap_price=target.vwap_price,
                mfi=target.mfi,
                total_budget=budget,
            )
            self.buy_plan_steps = [BuyPlanStep(**s) for s in result["steps"]]
            self.plan_type = result["plan_type"]
            self.plan_avg_price = result["avg_price"]
            self.plan_stop_loss = result["stop_loss"]
            self.plan_stop_loss_pct = result["stop_loss_pct"]
        except Exception as e:
            self.plan_type = f"계산 오류: {e}"

    async def select_stock(self, name: str):
        self.selected_name = name

        # whale 모드: whale_results에서 검색
        if self.scan_mode == "whale":
            w_target = self._find_whale_result(name)
            if not w_target:
                return
            self.selected_symbol = w_target.symbol
            self.selected_market = w_target.market
            self.selected_currency = "USD" if w_target.market in ("SP500", "NASDAQ", "US-ETF") else "KRW"
            self.selected_market_cap_str = "-"
            self.selected_pbr = 0.0
            self.selected_psr = 0.0
            self.selected_div_yield = "-"
            self.selected_mfi = 0.0
            self.selected_close = w_target.close
            self.selected_vwap_price = 0.0
            self.selected_vwap_gap = 0.0
            self.selected_condition = w_target.applied_step
            self.selected_holding_buy_price = 0.0
            self.selected_holding_quantity = 0.0
            self.selected_holding_memo = ""
            self.selected_is_holding = False
            self.buy_msg = ""
            self.sell_msg = ""
            self.bt_summary = BacktestSummary()
            self.equity_data = []
            self.trades_data = []
            self.bt_price_chart_data = []
            self.bt_buy_points = []
            self.bt_sell_points = []
            self.price_chart_data = []
            self.psr_chart_data = []
            self.close_date = ""
            self.whale_chart_data = []
            self.whale_highlights = []
            self.is_loading_chart = True
            self.active_tab = "analysis"
            yield

            try:
                import pandas as pd
                import FinanceDataReader as fdr
                from datetime import timedelta
                from utils.data_loader import QuantDataLoader
                from utils.indicators import TechnicalIndicators
                from utils.accumulation_indicators import (
                    analyze_whale_with_options, extract_highlights, compute_threshold,
                )

                vwap = int(self.vwap_period)
                loader = QuantDataLoader()
                _t1 = asyncio.create_task(asyncio.to_thread(loader.get_ohlcv, w_target.symbol, 600))
                while not _t1.done():
                    try:
                        df = await asyncio.wait_for(asyncio.shield(_t1), timeout=0.5)
                        break
                    except asyncio.TimeoutError:
                        yield
                else:
                    df = _t1.result()
                if df.empty:
                    self.status_msg = f"{w_target.name} 가격 데이터 없음"
                    return

                windows = sorted({vwap, 20, 60, 120})
                df = TechnicalIndicators.calculate_all(df, windows)
                display_df = df.tail(200)
                vwap_col = f"VWAP_{vwap}"

                def _v(val):
                    return round(float(val), 0) if not pd.isna(val) else None

                self.price_chart_data = [
                    {
                        "date": str(d.date()),
                        "종가": _v(row["Close"]),
                        "VWAP": _v(row.get(vwap_col)),
                        "MA20": _v(row.get("TWAP_20")),
                        "MA60": _v(row.get("TWAP_60")),
                        "MA120": _v(row.get("TWAP_120")),
                        "SMA120": _v(row.get("SMA_120")),
                    }
                    for d, row in display_df.iterrows()
                ]
                self.close_date = str(display_df.index[-1].date())

                # 세력 탐지 보조 차트
                is_us = w_target.market in {"SP500", "NASDAQ"}
                use_short_chart = self.use_short_filter and is_us
                hl_threshold = compute_threshold(self.use_alpha, use_short_chart)

                _INDEX_FDR = {"KOSPI": "KS11", "KOSDAQ": "KQ11", "KR-ETF": "KS11", "SP500": "^GSPC", "NASDAQ": "^IXIC", "US-ETF": "^GSPC"}
                end_dt = display_df.index[-1]
                start_dt = end_dt - timedelta(days=250)
                try:
                    _idx_code = _INDEX_FDR.get(w_target.market, "KS11")
                    _t_idx = asyncio.create_task(asyncio.to_thread(
                        fdr.DataReader, _idx_code,
                        start_dt.strftime("%Y-%m-%d"),
                        end_dt.strftime("%Y-%m-%d"),
                    ))
                    while not _t_idx.done():
                        try:
                            idx_df = await asyncio.wait_for(asyncio.shield(_t_idx), timeout=0.5)
                            break
                        except asyncio.TimeoutError:
                            yield
                    else:
                        idx_df = _t_idx.result()
                except Exception:
                    idx_df = pd.DataFrame()

                whale_full, _ = analyze_whale_with_options(
                    df.tail(200), idx_df,
                    use_alpha=self.use_alpha,
                    use_short_filter=use_short_chart,
                    threshold=hl_threshold,
                )
                self.whale_highlights = extract_highlights(whale_full, threshold=hl_threshold)
                self.whale_chart_data = [
                    {
                        "date": str(d.date()),
                        "OBV": round(float(row["OBV"]), 0) if not pd.isna(row.get("OBV", float("nan"))) else None,
                        "Short_Balance": round(float(row["Short_Balance"]), 0)
                            if "Short_Balance" in row.index and not pd.isna(row["Short_Balance"]) else None,
                        "Score": int(row.get("Accum_Score", 0)),
                    }
                    for d, row in whale_full.iterrows()
                ]
            except Exception as e:
                self.status_msg = f"차트 로드 오류: {e}"
            finally:
                self.is_loading_chart = False
            yield
            return

        # 퀀트 모드
        target = self._find_result(name)
        if not target:
            return

        self.selected_symbol = target.symbol
        self.selected_market = target.market_raw
        self.selected_currency = target.currency
        self.selected_market_cap_str = target.market_cap_str
        self.selected_pbr = target.pbr
        self.selected_psr = target.psr
        self.selected_div_yield = target.div_yield
        self.selected_mfi = target.mfi
        self.selected_close = target.close
        self.selected_vwap_price = target.vwap_price
        self.selected_vwap_gap = target.vwap_gap
        self.selected_condition = target.condition
        self.selected_holding_buy_price = 0.0
        self.selected_holding_quantity = 0.0
        self.selected_holding_memo = ""
        self.selected_is_holding = False

        buy, sell = InvestmentReasoning.generate_report(
            target.name, target.pbr, int(self.vwap_period),
            target.mfi, target.vwap_price, target.currency,
        )
        self.buy_msg = buy
        self.sell_msg = sell
        self.bt_summary = BacktestSummary()
        self.equity_data = []
        self.trades_data = []
        self.bt_price_chart_data = []
        self.bt_buy_points = []
        self.bt_sell_points = []
        self.price_chart_data = []
        self.psr_chart_data = []
        self.close_date = ""
        self.whale_chart_data = []
        self.whale_highlights = []
        self.is_loading_chart = True
        self.active_tab = "analysis"
        yield

        try:
            import pandas as pd
            from utils.data_loader import QuantDataLoader
            from utils.indicators import TechnicalIndicators
            vwap = int(self.vwap_period)
            loader = QuantDataLoader()
            _t1 = asyncio.create_task(asyncio.to_thread(loader.get_ohlcv, target.symbol, 600))
            while not _t1.done():
                try:
                    df = await asyncio.wait_for(asyncio.shield(_t1), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                df = _t1.result()
            df = TechnicalIndicators.calculate_all(df, [vwap, 20, 60, 120])
            display_df = df.tail(200)
            vwap_col = f"VWAP_{vwap}"

            def _v(val):
                return round(float(val), 0) if not pd.isna(val) else None

            self.price_chart_data = [
                {
                    "date": str(d.date()),
                    "종가": _v(row["Close"]),
                    "VWAP": _v(row[vwap_col]),
                    "MA20": _v(row["TWAP_20"]),
                    "MA60": _v(row["TWAP_60"]),
                    "MA120": _v(row["TWAP_120"]),
                    "SMA120": _v(row["SMA_120"]),
                }
                for d, row in display_df.iterrows()
            ]
            self.close_date = str(display_df.index[-1].date())
            # 분기별 PSR
            _t2 = asyncio.create_task(asyncio.to_thread(
                loader.get_quarterly_psr, target.symbol, target.market_raw
            ))
            while not _t2.done():
                try:
                    psr_data = await asyncio.wait_for(asyncio.shield(_t2), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                psr_data = _t2.result()
            self.psr_chart_data = psr_data

        except Exception:
            pass
        finally:
            self.is_loading_chart = False
        yield

    async def goto_analysis(self, code: str, name: str, is_us: bool = False):
        """추세추종 등 스캐너에서 분석 탭으로 이동 (code+name+is_us 기반)"""
        self.selected_symbol = code
        self.selected_name = name
        self.selected_market = self.market
        self.selected_currency = "USD" if is_us else "KRW"
        self.selected_market_cap_str = "-"
        self.selected_pbr = 0.0
        self.selected_psr = 0.0
        self.selected_div_yield = "-"
        self.selected_mfi = 0.0
        self.selected_close = 0.0
        self.selected_vwap_price = 0.0
        self.selected_vwap_gap = 0.0
        self.selected_condition = ""
        self.selected_holding_buy_price = 0.0
        self.selected_holding_quantity = 0.0
        self.selected_holding_memo = ""
        self.selected_is_holding = False
        self.buy_msg = ""
        self.sell_msg = ""
        self.bt_summary = BacktestSummary()
        self.equity_data = []
        self.trades_data = []
        self.bt_price_chart_data = []
        self.bt_buy_points = []
        self.bt_sell_points = []
        self.price_chart_data = []
        self.psr_chart_data = []
        self.close_date = ""
        self.whale_chart_data = []
        self.whale_highlights = []
        self.is_loading_chart = True
        self.active_tab = "analysis"
        yield

        try:
            import pandas as pd
            from utils.data_loader import QuantDataLoader
            from utils.indicators import TechnicalIndicators
            vwap = int(self.vwap_period)
            loader = QuantDataLoader()
            _t1 = asyncio.create_task(asyncio.to_thread(loader.get_ohlcv, code, 600))
            while not _t1.done():
                try:
                    df = await asyncio.wait_for(asyncio.shield(_t1), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                df = _t1.result()
            df = TechnicalIndicators.calculate_all(df, [vwap, 20, 60, 120])
            display_df = df.tail(200)
            vwap_col = f"VWAP_{vwap}"

            def _v(val):
                return round(float(val), 0) if not pd.isna(val) else None

            self.price_chart_data = [
                {
                    "date": str(d.date()),
                    "종가": _v(row["Close"]),
                    "VWAP": _v(row.get(vwap_col)),
                    "MA20": _v(row.get("TWAP_20")),
                    "MA60": _v(row.get("TWAP_60")),
                    "MA120": _v(row.get("TWAP_120")),
                    "SMA120": _v(row.get("SMA_120")),
                }
                for d, row in display_df.iterrows()
            ]
            self.close_date = str(display_df.index[-1].date())
            self.selected_close = float(df["Close"].iloc[-1])
            _t2 = asyncio.create_task(asyncio.to_thread(
                loader.get_quarterly_psr, code, self.market
            ))
            while not _t2.done():
                try:
                    psr_data = await asyncio.wait_for(asyncio.shield(_t2), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                psr_data = _t2.result()
            self.psr_chart_data = psr_data
        except Exception:
            pass
        finally:
            self.is_loading_chart = False
        yield

    async def load_trend_detail(self, code: str, entry_type: str, ma_period: int, entry_label: str):
        """추세추종 종목 보유기간별 EV 상세 백테스트"""
        self.trend_detail_code = code
        self.trend_detail_name = entry_label.split(" ")[0] if entry_label else code
        self.trend_detail_entry_label = entry_label
        self.trend_detail_rows = []
        self.trend_detail_loading = True
        yield

        try:
            from utils.data_loader import QuantDataLoader
            from utils.trend_scanner import calc_holding_period_ev
            loader = QuantDataLoader()
            _t1 = asyncio.create_task(asyncio.to_thread(loader.get_ohlcv, code, 1600))
            while not _t1.done():
                try:
                    df = await asyncio.wait_for(asyncio.shield(_t1), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                df = _t1.result()
            _t2 = asyncio.create_task(asyncio.to_thread(
                calc_holding_period_ev, df, entry_type, ma_period,
            ))
            while not _t2.done():
                try:
                    rows = await asyncio.wait_for(asyncio.shield(_t2), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                rows = _t2.result()
            for r in rows:
                r["code"] = code
            self.trend_detail_rows = rows
        except Exception as e:
            self.status_msg = f"상세 백테스트 오류: {e}"
        finally:
            self.trend_detail_loading = False
        yield

    async def load_seasonality(self, code: str, entry_type: str, ma_period: int, entry_label: str):
        """추세추종 종목 12개월 계절성 EV 분석"""
        self.season_code        = code
        self.season_entry_type  = entry_type
        self.season_ma_period   = ma_period
        self.season_entry_label = entry_label
        self.season_rows        = []
        self.season_loading     = True
        yield

        try:
            from utils.data_loader  import QuantDataLoader
            from utils.seasonality  import calc_monthly_seasonality
            loader = QuantDataLoader()
            _t1 = asyncio.create_task(asyncio.to_thread(loader.get_ohlcv, code, 1600))
            while not _t1.done():
                try:
                    df = await asyncio.wait_for(asyncio.shield(_t1), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                df = _t1.result()
            _t2 = asyncio.create_task(asyncio.to_thread(
                calc_monthly_seasonality, df, entry_type, ma_period, self.season_hold_days
            ))
            while not _t2.done():
                try:
                    rows = await asyncio.wait_for(asyncio.shield(_t2), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                rows = _t2.result()
            self.season_rows = rows
        except Exception as e:
            self.status_msg = f"계절성 분석 오류: {e}"
        finally:
            self.season_loading = False
        yield

    async def set_season_hold_days(self, days: int):
        """계절성 분석 보유기간 변경 후 재계산"""
        if days == self.season_hold_days:
            return
        self.season_hold_days = days
        if not self.season_code:
            return
        self.season_rows    = []
        self.season_loading = True
        yield

        try:
            from utils.data_loader  import QuantDataLoader
            from utils.seasonality  import calc_monthly_seasonality
            loader = QuantDataLoader()
            _t1 = asyncio.create_task(asyncio.to_thread(loader.get_ohlcv, self.season_code, 1600))
            while not _t1.done():
                try:
                    df = await asyncio.wait_for(asyncio.shield(_t1), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                df = _t1.result()
            _t2 = asyncio.create_task(asyncio.to_thread(
                calc_monthly_seasonality,
                df, self.season_entry_type, self.season_ma_period, self.season_hold_days,
            ))
            while not _t2.done():
                try:
                    rows = await asyncio.wait_for(asyncio.shield(_t2), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                rows = _t2.result()
            self.season_rows = rows
        except Exception as e:
            self.status_msg = f"계절성 분석 오류: {e}"
        finally:
            self.season_loading = False
        yield

    # ------------------------------------------------------------------
    # Async event handlers
    # ------------------------------------------------------------------

    def export_pdf(self):
        """분석 영역만 새 창에 복사해 인쇄 대화상자 실행."""
        return rx.call_script("""
(function() {
    var el = document.getElementById('analysis-print-area');
    if (!el) { window.print(); return; }

    // 현재 페이지의 모든 스타일시트 수집 (Radix CSS 변수 포함)
    var styles = Array.from(
        document.querySelectorAll('style, link[rel="stylesheet"]')
    ).map(function(s) { return s.outerHTML; }).join('');

    var w = window.open('', '_blank');
    w.document.open();
    w.document.write(
        '<!DOCTYPE html><html><head>' +
        '<meta charset="utf-8">' +
        '<title>QuantMaster - 분석 리포트</title>' +
        styles +
        '<style>' +
        '@page { size: A4 portrait; margin: 1.5cm; }' +
        'body { padding: 24px; background: white; }' +
        '.recharts-wrapper, table { page-break-inside: avoid; break-inside: avoid; }' +
        '.no-print { display: none !important; }' +
        '</style>' +
        '</head><body>' +
        el.outerHTML +
        '</body></html>'
    );
    w.document.close();
    setTimeout(function() { w.print(); }, 800);
})();
""")

    async def run_scan(self):
        if self.scan_mode == "whale":
            # ── 세력 탐지 스캔 (단계별 점진 완화 + 타임아웃) ────────────
            import time as _time
            from accumulation_scanner import AccumulationScanner, _RELAXATION_STEPS

            self.is_scanning = True
            self.whale_stop_requested = False
            self.whale_results = []
            self.whale_progress = ""
            self.status_msg = "세력 탐지 준비 중..."
            yield

            max_seconds = float(self.whale_max_minutes * 60)
            scanner = AccumulationScanner()
            found: dict = {}
            remaining: list = []
            ctx: dict = {}

            try:
                # 1. 공통 초기화 (종목 목록 + 지수 데이터)
                self.status_msg = "시장 데이터 로드 중..."
                yield
                _prep_task = asyncio.create_task(asyncio.to_thread(
                    scanner.prepare,
                    self.market,
                    self.use_alpha,
                    self.use_short_filter,
                ))
                while not _prep_task.done():
                    try:
                        ctx = await asyncio.wait_for(asyncio.shield(_prep_task), timeout=0.5)
                        break
                    except asyncio.TimeoutError:
                        if self.whale_stop_requested:
                            self.status_msg = "탐색이 중단되었습니다."
                            return
                        yield
                else:
                    ctx = _prep_task.result()
                if not ctx:
                    self.status_msg = "시장 데이터 로드 실패"
                    return

                remaining = list(ctx["symbols"])
                total = len(remaining)
                n_steps = len(_RELAXATION_STEPS)
                start_t = _time.monotonic()

                # 2. 단계별 완화 루프
                for step_idx, (step_label, obv_mult, alpha_thresh, sig_win, th_ratio) in enumerate(_RELAXATION_STEPS):
                    if len(found) >= 10 or not remaining:
                        break

                    # 사용자 중단 요청 확인
                    if self.whale_stop_requested:
                        self.status_msg = (
                            f"탐색이 중단되었습니다. 현재까지 {len(found)}개 종목을 탐지했습니다."
                        )
                        break

                    elapsed = _time.monotonic() - start_t
                    if elapsed >= max_seconds:
                        self.status_msg = (
                            f"시간 초과 ({self.whale_max_minutes}분). "
                            f"{len(found)}개 탐지"
                        )
                        break

                    remain_secs = max_seconds - elapsed
                    steps_left = n_steps - step_idx
                    step_timeout = remain_secs / max(1, steps_left)

                    # 진행률 텍스트 업데이트
                    processed = total - len(remaining)
                    pct = int(processed / total * 100) if total else 0
                    mins = int(elapsed // 60)
                    secs = int(elapsed % 60)
                    step_th = max(int(ctx["threshold"] * th_ratio), 25)
                    self.whale_progress = (
                        f"단계 {step_idx+1}/{n_steps} ({step_label})  |  "
                        f"종목 {processed}/{total} ({pct}%)  |  "
                        f"탐지 {len(found)}/10  |  "
                        f"기준점수 {step_th}  |  "
                        f"경과 {mins}분 {secs:02d}초"
                    )
                    self.status_msg = self.whale_progress
                    yield

                    _batch_task = asyncio.create_task(asyncio.to_thread(
                        scanner._scan_batch,
                        remaining,
                        ctx,
                        self.use_alpha,
                        obv_mult,
                        alpha_thresh,
                        sig_win,
                        step_label,
                        step_timeout,
                        th_ratio,
                    ))
                    while not _batch_task.done():
                        try:
                            new = await asyncio.wait_for(asyncio.shield(_batch_task), timeout=0.5)
                            break
                        except asyncio.TimeoutError:
                            if self.whale_stop_requested:
                                self.status_msg = (
                                    f"탐색이 중단되었습니다. 현재까지 {len(found)}개 종목을 탐지했습니다."
                                )
                                self.whale_stop_requested = False
                                yield
                                return
                            yield
                    else:
                        new = _batch_task.result()
                    new_found = False
                    for r in new:
                        if r["Symbol"] not in found:
                            found[r["Symbol"]] = r
                            new_found = True
                    remaining = [s for s in remaining if s not in found]

                    # 새 종목이 발견됐으면 즉시 테이블 갱신
                    if new_found and found:
                        import pandas as pd
                        df_live = (
                            pd.DataFrame(found.values())
                            .sort_values("Score", ascending=False)
                            .head(10)
                            .reset_index(drop=True)
                        )
                        self.whale_results = [
                            WhaleScanResult(
                                name=str(row["Name"]),
                                symbol=str(row["Symbol"]),
                                market=str(row["Market"]),
                                signal_date=str(row["Signal_Date"]),
                                score=int(row["Score"]),
                                signal_type=str(row["Signal_Type"]),
                                obv_spike=bool(row["OBV_Spike"]),
                                breakout=bool(row["Breakout"]),
                                alpha=bool(row["Alpha"]),
                                short_cover=bool(row["Short_Cover"]),
                                close=float(row["Close"]),
                                volume_ratio=float(row["Volume_Ratio"]),
                                applied_step=str(row.get("Applied_Step", "원본")),
                            )
                            for _, row in df_live.iterrows()
                        ]
                        yield  # 즉시 UI 반영

                    if len(found) >= 10:
                        break

                # 3. 최종 상태 메시지
                elapsed = _time.monotonic() - start_t
                mins = int(elapsed // 60)
                secs = int(elapsed % 60)
                if found:
                    self.status_msg = (
                        f"{len(self.whale_results)}개 세력 매집 종목 탐지 "
                        f"(소요 {mins}분 {secs:02d}초)"
                    )
                else:
                    self.status_msg = "탐지된 세력 매집 종목 없음"
                self.whale_progress = ""

            except Exception as e:
                self.status_msg = f"오류: {e}"
                self.whale_progress = ""
            finally:
                self.is_scanning = False
                self.whale_stop_requested = False
            yield
            return

        # ── 눌림목 스캔 ──────────────────────────────────────────────────
        if self.scan_mode == "pullback":
            from utils.pullback_scanner import scan_pullback_stocks
            self.is_scanning = True
            self.scan_stop_requested = False
            self.pullback_results = []
            self.scan_warning = ""
            mkt_map = {"SP500": "SP500", "NASDAQ": "SP500",
                       "KR-ETF": "KOSPI", "US-ETF": "SP500"}
            mkt = mkt_map.get(self.market, self.market)
            self.status_msg = f"{mkt} 눌림목 종목 탐색 중... (약 1~2분 소요)"
            yield
            try:
                _task = asyncio.create_task(asyncio.to_thread(
                    scan_pullback_stocks,
                    mkt,
                    self.pullback_min_mktcap,
                    self.pullback_min_dip[0],
                    self.pullback_max_rsi[0],
                    0.0,
                    30,
                    150,
                    90,
                ))
                while not _task.done():
                    try:
                        raw = await asyncio.wait_for(asyncio.shield(_task), timeout=0.5)
                        break
                    except asyncio.TimeoutError:
                        if self.scan_stop_requested:
                            self.status_msg = "스캔이 중단되었습니다."
                            self.scan_stop_requested = False
                            yield
                            return
                        yield
                else:
                    raw = _task.result()
                self.pullback_results = list(raw)
                warn = getattr(raw, "warning", "")
                if warn:
                    self.scan_warning = warn
                cnt = len(raw)
                self.status_msg = (
                    f"눌림목 종목 {cnt}개 발굴 완료" if cnt
                    else "조건을 만족하는 종목이 없습니다. 낙폭·RSI 조건을 완화해보세요."
                )
            except Exception as e:
                self.status_msg = f"오류: {e}"
            finally:
                self.is_scanning = False
            yield
            return

        # ── 추세추종 스캔 ────────────────────────────────────────────────
        if self.scan_mode == "trend":
            from utils.trend_scanner import scan_trend_following
            self.is_scanning   = True
            self.scan_stop_requested = False
            self.trend_results = []
            self.trend_progress = ""
            self.scan_warning  = ""
            mkt_map = {"KR-ETF": "KOSPI", "US-ETF": "SP500"}
            mkt = mkt_map.get(self.market, self.market)
            mode_label = {"relative": "RS90+", "absolute": "절대강도", "both": "RS90+·절대강도"}
            self.status_msg = (
                f"{mkt} 추세추종 종목 탐색 중 ({mode_label.get(self.trend_filter_mode, '')}) "
                f"... (약 2~4분 소요)"
            )
            yield

            done_ref = [0]
            total_ref = [0]

            def _progress(done, total):
                done_ref[0]  = done
                total_ref[0] = total

            try:
                # CLOSE_WAIT 방지: 최대 600초 타임아웃 + 주기적 yield(heartbeat)
                scan_task = asyncio.create_task(asyncio.to_thread(
                    scan_trend_following,
                    mkt,
                    self.trend_filter_mode,
                    float(self.trend_min_mktcap),
                    30,
                    150,
                    _progress,
                ))
                while not scan_task.done():
                    try:
                        raw = await asyncio.wait_for(asyncio.shield(scan_task), timeout=0.5)
                        break
                    except asyncio.TimeoutError:
                        d, t = done_ref[0], total_ref[0]
                        if t > 0:
                            self.trend_progress = f"{d}/{t}개 수집 중..."
                        if self.scan_stop_requested:
                            self.status_msg = "스캔이 중단되었습니다."
                            self.scan_stop_requested = False
                            yield
                            return
                        yield
                else:
                    raw = scan_task.result()
                self.trend_results = list(raw)
                warn = getattr(raw, "warning", "")
                if warn:
                    self.scan_warning = warn
                cnt = len(raw)
                self.status_msg = (
                    f"추세추종 신호 {cnt}개 발굴 완료" if cnt
                    else "신호 없음 — 필터 조건(RS90/절대강도)을 완화하거나 시장을 바꿔보세요."
                )
            except Exception as e:
                self.status_msg = f"오류: {e}"
            finally:
                self.is_scanning   = False
                self.trend_progress = ""
            yield
            return

        # ── 하락방어 스캔 ────────────────────────────────────────────────
        if self.scan_mode == "defensive":
            from utils.defensive_scanner import scan_defensive_stocks
            self.is_scanning = True
            self.scan_stop_requested = False
            self.defensive_results = []
            mkt = self.market if self.market in ("KOSPI", "KOSDAQ") else "KOSPI"
            self.status_msg = f"{mkt} 하락방어 종목 분석 중... (약 1~2분 소요)"
            yield
            try:
                _task = asyncio.create_task(asyncio.to_thread(
                    scan_defensive_stocks,
                    mkt,
                    self.defensive_period,
                    self.defensive_max_beta[0],
                    self.defensive_min_mktcap,
                    30,
                ))
                while not _task.done():
                    try:
                        raw = await asyncio.wait_for(asyncio.shield(_task), timeout=0.5)
                        break
                    except asyncio.TimeoutError:
                        if self.scan_stop_requested:
                            self.status_msg = "스캔이 중단되었습니다."
                            self.scan_stop_requested = False
                            yield
                            return
                        yield
                else:
                    raw = _task.result()
                self.defensive_results = raw
                cnt = len(raw)
                self.status_msg = (
                    f"하락방어 종목 {cnt}개 발굴 완료" if cnt else "조건을 만족하는 종목이 없습니다."
                )
            except Exception as e:
                self.status_msg = f"오류: {e}"
            finally:
                self.is_scanning = False
            yield
            return

        # ── 종목 모멘텀 스캔 ─────────────────────────────────────────────
        if self.scan_mode == "stock_momentum":
            from utils.stock_scanner import scan_stock_momentum
            self.is_scanning = True
            self.scan_stop_requested = False
            self.stock_momentum_results = []
            self.scan_warning = ""
            mkt_map = {
                "SP500": "SP500", "NASDAQ": "SP500",
                "KR-ETF": "KOSPI", "US-ETF": "SP500",
            }
            mkt = mkt_map.get(self.market, self.market)
            if mkt not in ("KOSPI", "KOSDAQ", "SP500"):
                mkt = "KOSPI"
            period_lbl = {"1W": "1주", "1M": "1개월", "2M": "2개월", "3M": "3개월"}.get(
                self.stock_momentum_period, ""
            )
            self.status_msg = f"{mkt} {period_lbl} 모멘텀 스캔 중... (약 1~2분 소요)"
            yield
            try:
                _task = asyncio.create_task(asyncio.to_thread(
                    scan_stock_momentum,
                    mkt,
                    self.stock_momentum_period,
                    self.stock_momentum_mktcap,
                    30,
                ))
                while not _task.done():
                    try:
                        raw = await asyncio.wait_for(asyncio.shield(_task), timeout=0.5)
                        break
                    except asyncio.TimeoutError:
                        if self.scan_stop_requested:
                            self.status_msg = "스캔이 중단되었습니다."
                            self.scan_stop_requested = False
                            yield
                            return
                        yield
                else:
                    raw = _task.result()
                self.stock_momentum_results = list(raw)
                self.scan_warning = getattr(raw, "warning", "")
                cnt = len(raw)
                self.status_msg = (
                    f"모멘텀 {cnt}개 종목 발굴 완료" if cnt
                    else "조건을 만족하는 종목이 없습니다."
                )
            except Exception as e:
                self.status_msg = f"오류: {e}"
            finally:
                self.is_scanning = False
            yield
            return

        # ── 퀀트 스캔 ────────────────────────────────────────────────────
        self.is_scanning = True
        self.scan_stop_requested = False
        self.status_msg = "시장 데이터 수집 중..."
        self.scan_results = []
        yield

        try:
            scanner = QuantScanner()
            vwap = int(self.vwap_period)
            _task = asyncio.create_task(asyncio.to_thread(
                scanner.run_advanced_scan,
                self.pbr_limit[0],
                vwap,
                10,
                self.market,
                self.min_cap_label,
            ))
            while not _task.done():
                try:
                    results = await asyncio.wait_for(asyncio.shield(_task), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    if self.scan_stop_requested:
                        self.status_msg = "스캔이 중단되었습니다."
                        self.scan_stop_requested = False
                        yield
                        return
                    yield
            else:
                results = _task.result()

            self.scan_results = [
                ScanResult(
                    name=str(row["Name"]),
                    symbol=str(row["Symbol"]),
                    market_raw=str(row.get("Market", "KOSPI")),
                    pbr=float(row["PBR"]),
                    psr=float(row["PSR"]) if not math.isnan(float(row.get("PSR", float("nan")))) else 0.0,
                    mfi=float(row["MFI"]),
                    obv_ok=bool(row["OBV_OK"]),
                    vwap_price=float(row["VWAP_Price"]),
                    close=float(row["Close"]),
                    vwap_gap=float(row["VWAP_Gap"]),
                    condition=str(row["Condition"]),
                    applied_pbr=float(row["Applied_PBR"]),
                    applied_gpa=float(row["Applied_GPA"]),
                    applied_mfi=int(row["Applied_MFI"]),
                    applied_obv=bool(row["Applied_OBV"]),
                    applied_min_cap=str(row.get("Applied_MinCap", "전체")),
                    currency=str(row.get("Currency", "KRW")),
                    market_cap_str=str(row.get("MarketCap_Str", "-")),
                    div_yield=str(row.get("DivYield", "-")),
                )
                for _, row in results.iterrows()
            ]
            count = len(self.scan_results)
            self.status_msg = (
                f"{count}개 종목 발굴 완료" if count else "조건을 만족하는 종목이 없습니다."
            )
        except Exception as e:
            self.status_msg = f"오류: {e}"
        finally:
            self.is_scanning = False
        yield

    async def run_backtest(self):
        # 퀀트(현재+히스토리) 및 세력탐지(현재+히스토리) 모두에서 종목 검색
        quant_target = self._find_result(self.selected_name)
        whale_target = next(
            (r for r in self.whale_results if r.name == self.selected_name),
            next((r for r in self.history_whale_results if r.name == self.selected_name), None),
        )
        found = quant_target or whale_target
        if not found:
            self.status_msg = "종목을 먼저 선택하세요."
            return
        target_name   = found.name
        target_symbol = found.symbol

        self.is_backtesting = True
        self.status_msg = f"{target_name} 백테스트 실행 중..."
        yield

        try:
            bt = Backtester()
            _task = asyncio.create_task(asyncio.to_thread(
                bt.run,
                target_symbol,
                target_name,
                int(self.vwap_period),
            ))
            while not _task.done():
                try:
                    result = await asyncio.wait_for(asyncio.shield(_task), timeout=0.5)
                    break
                except asyncio.TimeoutError:
                    yield
            else:
                result = _task.result()

            if result:
                self.bt_summary = BacktestSummary(
                    total_return=round(result["Total_Return"], 2),
                    mdd=round(result["MDD"], 2),
                    win_rate=round(result["Win_Rate"], 1),
                    avg_return=round(result["Avg_Return"], 2),
                    sharpe=round(result["Sharpe"], 2),
                    trade_count=int(result["Trades"]),
                )
                eq = result["Equity_Curve"]
                self.equity_data = [
                    {"date": str(d.date()), "value": round(float(v), 0)}
                    for d, v in zip(eq.index, eq.values)
                ]
                trades_df = result["Trades_DF"]
                if not trades_df.empty:
                    self.trades_data = trades_df.to_dict("records")

                # 백테스트 가격 차트 데이터 빌드 (VWAP + MA)
                ohlcv = result["OHLCV"]
                vwap_col = result["VWAP_Col"]
                from utils.indicators import TechnicalIndicators as _TI
                ohlcv = _TI.calculate_all(ohlcv, [20, 60, 120])

                import math as _math
                def _v(val):
                    return round(float(val), 0) if val is not None and not (isinstance(val, float) and _math.isnan(val)) else None

                self.bt_price_chart_data = [
                    {
                        "date":   str(d.date()),
                        "종가":   _v(row["Close"]),
                        "VWAP":   _v(row.get(vwap_col)),
                        "MA20":   _v(row.get("TWAP_20")),
                        "MA60":   _v(row.get("TWAP_60")),
                        "MA120":  _v(row.get("TWAP_120")),
                        "SMA120": _v(row.get("SMA_120")),
                    }
                    for d, row in ohlcv.iterrows()
                ]

                # 매수/매도 마커 (ReferenceDot 용)
                if not trades_df.empty:
                    self.bt_buy_points = [
                        {"date": str(row["Entry"]), "가격": float(row["Entry_Price"])}
                        for _, row in trades_df.iterrows()
                    ]
                    self.bt_sell_points = [
                        {"date": str(row["Exit"]), "가격": float(row["Exit_Price"])}
                        for _, row in trades_df.iterrows()
                    ]

                self.status_msg = "백테스트 완료"
            else:
                self.status_msg = "데이터 부족으로 백테스트 불가"
        except Exception as e:
            self.status_msg = f"백테스트 오류: {e}"
        finally:
            self.is_backtesting = False
        yield


# ---------------------------------------------------------------------------
# UI Components
# ---------------------------------------------------------------------------


def sidebar_controls() -> rx.Component:
    """스캐너 탭 상단 컨트롤 패널 — 컴팩트 수평 레이아웃."""
    # ── 공통: 모드 + 시장 셀렉트 ──────────────────────────────
    base_row = rx.hstack(
        rx.text("모드", size="1", color="gray", white_space="nowrap"),
        rx.select.root(
            rx.select.trigger(placeholder="모드"),
            rx.select.content(
                rx.select.item("밸류 돌파", value="quant"),
                rx.select.item("세력 탐지", value="whale"),
                rx.select.item("하락방어", value="defensive"),
                rx.select.item("눌림목", value="pullback"),
                rx.select.item("추세추종", value="trend"),
                rx.select.item("모멘텀 스캔", value="stock_momentum"),
            ),
            value=State.scan_mode,
            on_change=State.set_scan_mode,
            size="1",
        ),
        rx.text("시장", size="1", color="gray", white_space="nowrap"),
        rx.select.root(
            rx.select.trigger(placeholder="시장"),
            rx.select.content(
                rx.select.group(
                    rx.select.label("한국 주식"),
                    rx.select.item("KOSPI",  value="KOSPI"),
                    rx.select.item("KOSDAQ", value="KOSDAQ"),
                ),
                rx.select.separator(),
                rx.select.group(
                    rx.select.label("한국 ETF"),
                    rx.select.item("KR-ETF", value="KR-ETF"),
                ),
                rx.select.separator(),
                rx.select.group(
                    rx.select.label("미국"),
                    rx.select.item("S&P 500", value="SP500"),
                    rx.select.item("NASDAQ",  value="NASDAQ"),
                ),
                rx.select.separator(),
                rx.select.group(
                    rx.select.label("미국 ETF"),
                    rx.select.item("US-ETF",  value="US-ETF"),
                ),
            ),
            value=State.market,
            on_change=State.set_market,
            size="1",
        ),
        spacing="2",
        align="center",
        wrap="wrap",
        flex="1",
    )

    # ── 퀀트 전용 옵션 행 ──────────────────────────────────────
    quant_opts = rx.hstack(
        rx.text("PBR", size="1", color="gray", white_space="nowrap"),
        rx.text(State.pbr_limit[0], size="1", white_space="nowrap"),
        rx.slider(
            min=0.5, max=2.0, step=0.1,
            value=State.pbr_limit,
            on_change=State.set_pbr_limit,
            width="140px",
        ),
        rx.text("시총", size="1", color="gray", white_space="nowrap"),
        rx.select.root(
            rx.select.trigger(placeholder="시총"),
            rx.select.content(
                rx.select.item("전체",  value="전체"),
                rx.select.item("소형주+", value="소형주+"),
                rx.select.item("중형주+", value="중형주+"),
                rx.select.item("대형주+", value="대형주+"),
            ),
            value=State.min_cap_label,
            on_change=State.set_min_cap_label,
            size="1",
        ),
        rx.text("VWAP", size="1", color="gray", white_space="nowrap"),
        rx.select.root(
            rx.select.trigger(placeholder="기간"),
            rx.select.content(
                rx.select.item("20일",  value="20"),
                rx.select.item("60일",  value="60"),
                rx.select.item("120일", value="120"),
            ),
            value=State.vwap_period,
            on_change=State.set_vwap_period,
            size="1",
        ),
        spacing="2",
        align="center",
        wrap="wrap",
    )

    # ── 세력 탐지 전용 옵션 행 ─────────────────────────────────
    whale_opts = rx.hstack(
        rx.checkbox(checked=State.use_alpha, on_change=State.set_use_alpha),
        rx.text("알파 필터", size="1"),
        rx.separator(orientation="vertical", size="1"),
        rx.checkbox(checked=State.use_short_filter, on_change=State.set_use_short_filter),
        rx.text("공매도 필터", size="1"),
        rx.separator(orientation="vertical", size="1"),
        rx.text("최대", size="1", color="gray"),
        rx.input(
            value=State.whale_max_minutes,
            on_change=State.set_whale_max_minutes,
            type="number", min="1", max="30",
            width="56px", size="1",
        ),
        rx.text("분", size="1", color="gray"),
        spacing="2",
        align="center",
        wrap="wrap",
    )

    # ── 하락방어 전용 옵션 행 ──────────────────────────────────
    defensive_opts = rx.hstack(
        rx.text("기간", size="1", color="gray"),
        rx.button("2일",   size="1", variant=rx.cond(State.defensive_period == 2,   "solid", "soft"), on_click=State.set_defensive_period(2)),
        rx.button("5일",   size="1", variant=rx.cond(State.defensive_period == 5,   "solid", "soft"), on_click=State.set_defensive_period(5)),
        rx.button("30일",  size="1", variant=rx.cond(State.defensive_period == 30,  "solid", "soft"), on_click=State.set_defensive_period(30)),
        rx.button("60일",  size="1", variant=rx.cond(State.defensive_period == 60,  "solid", "soft"), on_click=State.set_defensive_period(60)),
        rx.button("120일", size="1", variant=rx.cond(State.defensive_period == 120, "solid", "soft"), on_click=State.set_defensive_period(120)),
        rx.separator(orientation="vertical", size="1"),
        rx.text("Beta", size="1", color="gray"),
        rx.text(State.defensive_max_beta[0], size="1"),
        rx.slider(min=0.3, max=1.0, step=0.1, value=State.defensive_max_beta,
                  on_change=State.set_defensive_max_beta, width="100px"),
        rx.separator(orientation="vertical", size="1"),
        rx.text("시총", size="1", color="gray"),
        rx.button("1조+",   size="1", variant=rx.cond(State.defensive_min_mktcap == 10_000, "solid", "soft"), on_click=State.set_defensive_min_mktcap(10_000)),
        rx.button("3천억+", size="1", variant=rx.cond(State.defensive_min_mktcap == 3_000,  "solid", "soft"), on_click=State.set_defensive_min_mktcap(3_000)),
        rx.button("전체",   size="1", variant=rx.cond(State.defensive_min_mktcap == 0,      "solid", "soft"), on_click=State.set_defensive_min_mktcap(0)),
        spacing="2",
        align="center",
        wrap="wrap",
    )

    # ── 눌림목 전용 옵션 행 ───────────────────────────────────────
    pullback_opts = rx.hstack(
        rx.text("1W낙폭≥", size="1", color="gray", white_space="nowrap"),
        rx.text(State.pullback_min_dip[0], size="1"),
        rx.text("%", size="1", color="gray"),
        rx.slider(min=-15, max=-2, step=1, value=State.pullback_min_dip,
                  on_change=State.set_pullback_min_dip, width="100px"),
        rx.separator(orientation="vertical", size="1"),
        rx.text("RSI≤", size="1", color="gray", white_space="nowrap"),
        rx.text(State.pullback_max_rsi[0], size="1"),
        rx.slider(min=25, max=60, step=5, value=State.pullback_max_rsi,
                  on_change=State.set_pullback_max_rsi, width="80px"),
        rx.separator(orientation="vertical", size="1"),
        rx.text("시총", size="1", color="gray"),
        rx.button("3천억+", size="1",
            variant=rx.cond(State.pullback_min_mktcap == 3_000, "solid", "soft"),
            on_click=State.set_pullback_min_mktcap(3_000)),
        rx.button("1조+", size="1",
            variant=rx.cond(State.pullback_min_mktcap == 10_000, "solid", "soft"),
            on_click=State.set_pullback_min_mktcap(10_000)),
        rx.button("전체", size="1",
            variant=rx.cond(State.pullback_min_mktcap == 0, "solid", "soft"),
            on_click=State.set_pullback_min_mktcap(0)),
        spacing="2",
        align="center",
        wrap="wrap",
    )

    # ── 추세추종 전용 옵션 행 ────────────────────────────────────
    trend_opts = rx.hstack(
        rx.text("필터", size="1", color="gray", white_space="nowrap"),
        rx.button("RS90+", size="1",
            variant=rx.cond(State.trend_filter_mode == "relative", "solid", "soft"),
            on_click=State.set_trend_filter_mode("relative")),
        rx.button("절대강도", size="1",
            variant=rx.cond(State.trend_filter_mode == "absolute", "solid", "soft"),
            on_click=State.set_trend_filter_mode("absolute")),
        rx.button("RS90+·절대강도", size="1",
            variant=rx.cond(State.trend_filter_mode == "both", "solid", "soft"),
            on_click=State.set_trend_filter_mode("both")),
        rx.separator(orientation="vertical", size="1"),
        rx.text("시총", size="1", color="gray"),
        rx.button("3천억+", size="1",
            variant=rx.cond(State.trend_min_mktcap == 3_000, "solid", "soft"),
            on_click=State.set_trend_min_mktcap(3_000)),
        rx.button("1조+", size="1",
            variant=rx.cond(State.trend_min_mktcap == 10_000, "solid", "soft"),
            on_click=State.set_trend_min_mktcap(10_000)),
        rx.button("전체", size="1",
            variant=rx.cond(State.trend_min_mktcap == 0, "solid", "soft"),
            on_click=State.set_trend_min_mktcap(0)),
        rx.cond(
            State.trend_progress != "",
            rx.text(State.trend_progress, size="1", color="gray"),
            rx.text(""),
        ),
        spacing="2",
        align="center",
        wrap="wrap",
    )

    # ── 종목 모멘텀 전용 옵션 행 ────────────────────────────────
    momentum_scan_opts = rx.hstack(
        rx.text("기간", size="1", color="gray"),
        rx.button("1주",   size="1", variant=rx.cond(State.stock_momentum_period == "1W", "solid", "soft"), on_click=State.set_stock_momentum_period("1W")),
        rx.button("1개월", size="1", variant=rx.cond(State.stock_momentum_period == "1M", "solid", "soft"), on_click=State.set_stock_momentum_period("1M")),
        rx.button("2개월", size="1", variant=rx.cond(State.stock_momentum_period == "2M", "solid", "soft"), on_click=State.set_stock_momentum_period("2M")),
        rx.button("3개월", size="1", variant=rx.cond(State.stock_momentum_period == "3M", "solid", "soft"), on_click=State.set_stock_momentum_period("3M")),
        rx.separator(orientation="vertical", size="1"),
        rx.text("시총", size="1", color="gray"),
        rx.button("3천억+", size="1", variant=rx.cond(State.stock_momentum_mktcap == 3_000,  "solid", "soft"), on_click=State.set_stock_momentum_mktcap(3_000)),
        rx.button("1조+",   size="1", variant=rx.cond(State.stock_momentum_mktcap == 10_000, "solid", "soft"), on_click=State.set_stock_momentum_mktcap(10_000)),
        rx.button("전체",   size="1", variant=rx.cond(State.stock_momentum_mktcap == 0,      "solid", "soft"), on_click=State.set_stock_momentum_mktcap(0)),
        spacing="2",
        align="center",
        wrap="wrap",
    )

    # ── 실행 버튼 그룹 ─────────────────────────────────────────
    action_btns = rx.hstack(
        rx.button(
            rx.cond(State.is_scanning, rx.spinner(size="1"), rx.text("스캔 실행")),
            on_click=State.run_scan,
            disabled=State.is_scanning,
            color_scheme="blue",
            size="2",
        ),
        rx.cond(
            State.is_scanning & (State.scan_mode == "whale"),
            rx.button(
                rx.cond(State.whale_stop_requested, "중단 중...", "탐색 중단"),
                on_click=State.stop_whale_scan,
                disabled=State.whale_stop_requested,
                color_scheme="red", variant="soft", size="2",
            ),
        ),
        rx.cond(
            State.scan_mode == "quant",
            rx.button("저장", on_click=State.save_scan,
                disabled=State.scan_results.length() == 0,
                color_scheme="green", variant="soft", size="2"),
            rx.button("저장", on_click=State.save_whale_scan,
                disabled=State.whale_results.length() == 0,
                color_scheme="green", variant="soft", size="2"),
        ),
        spacing="2",
        align="center",
        flex_shrink="0",
    )

    return rx.vstack(
        # 행1: 모드·시장 + 실행버튼
        rx.flex(
            base_row,
            action_btns,
            width="100%",
            justify="between",
            align="center",
            gap="3",
            wrap="wrap",
        ),
        # 행2: 모드별 옵션
        rx.cond(
            State.scan_mode == "quant",
            quant_opts,
            rx.cond(
                State.scan_mode == "whale",
                whale_opts,
                rx.cond(
                    State.scan_mode == "stock_momentum",
                    momentum_scan_opts,
                    rx.cond(
                        State.scan_mode == "pullback",
                        pullback_opts,
                        rx.cond(
                            State.scan_mode == "trend",
                            trend_opts,
                            defensive_opts,
                        ),
                    ),
                ),
            ),
        ),
        # 행3: 모드 설명
        rx.cond(
            State.scan_mode == "quant",
            rx.callout.root(
                rx.callout.text("💡 저PBR·고GPA 종목 중 VWAP 돌파 + MFI·OBV 스마트머니 유입을 확인하는 가치+기술 복합 스캔. 결과 저장 후 히스토리에서 재조회 가능."),
                color_scheme="blue", variant="surface", size="1",
            ),
            rx.cond(
                State.scan_mode == "whale",
                rx.callout.root(
                    rx.callout.text("💡 OBV 급등·가격 돌파·지수 대비 알파·숏커버 신호를 복합 채점해 세력 매집 가능성이 높은 종목을 탐지. 급등 초기 포착에 특화."),
                    color_scheme="amber", variant="surface", size="1",
                ),
                rx.cond(
                    State.scan_mode == "defensive",
                    rx.callout.root(
                        rx.callout.text("💡 하락장에서 시장 대비 낙폭이 작고 반등력이 강한 종목을 Beta·RS·Downside Capture로 선별. KOSPI/KOSDAQ 전용."),
                        color_scheme="green", variant="surface", size="1",
                    ),
                    rx.cond(
                        State.scan_mode == "trend",
                        rx.callout.root(
                            rx.callout.text("💡 RS90+ 강세 종목에서 EMA 눌림목·신고가 돌파·박스권 돌파 신호를 포착. EV(기대값)·반감기 3년 가중으로 현재 잘 작동하는 패턴 순위 정렬. (방법론: 《시장의 마법사》 프롤리히·쿨라매기)"),
                            color_scheme="indigo", variant="surface", size="1",
                        ),
                        rx.callout.root(
                            rx.callout.text("💡 하루 급등이 아닌 1주~3개월 꾸준한 우상향 종목을 탐색. 삼성전기·LG이노텍 류 소재·부품株 발굴에 적합. 시총 상위 300개 기준."),
                            color_scheme="violet", variant="surface", size="1",
                        ),
                    ),
                ),
            ),
        ),
        # 세력 탐지 진행률
        rx.cond(
            (State.scan_mode == "whale") & (State.whale_progress != ""),
            rx.box(
                rx.text(State.whale_progress, size="1", color="blue", white_space="pre-wrap"),
                padding="6px 10px",
                border_radius="6px",
                background="var(--blue-2)",
                border="1px solid var(--blue-4)",
                width="100%",
            ),
        ),
        rx.cond(
            State.status_msg != "",
            rx.text(State.status_msg, size="1", color="gray"),
        ),
        spacing="2",
        width="100%",
    )




def scanner_tab() -> rx.Component:
    controls = rx.card(
        sidebar_controls(),
        variant="surface",
        width="100%",
    )
    return rx.vstack(
        controls,
        rx.cond(
            State.scan_mode == "pullback",
            pullback_scanner_table(),
            rx.cond(
            State.scan_mode == "trend",
            trend_scanner_table(),
            rx.cond(
            State.scan_mode == "defensive",
            defensive_scanner_table(),
            rx.cond(
                State.scan_mode == "whale",
                whale_scanner_table(),
                rx.cond(
                    State.scan_mode == "stock_momentum",
                    stock_momentum_table(),
                    rx.cond(
                        State.scan_results.length() == 0,
                    rx.center(
                        rx.text("스캔 실행 버튼을 눌러 결과를 조회하세요.", color="gray"),
                        height="200px",
                    ),
                rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("종목명"),
                    rx.table.column_header_cell("심볼"),
                    rx.table.column_header_cell("시가총액"),
                    rx.table.column_header_cell("PBR"),
                    rx.table.column_header_cell("PSR"),
                    rx.table.column_header_cell("배당률"),
                    rx.table.column_header_cell("MFI"),
                    rx.table.column_header_cell("현재가"),
                    rx.table.column_header_cell("VWAP"),
                    rx.table.column_header_cell("괴리율(%)"),
                    rx.table.column_header_cell("조건"),
                    rx.table.column_header_cell(""),
                )
            ),
            rx.table.body(
                rx.foreach(
                    State.scan_results,
                    lambda r: rx.table.row(
                        rx.table.cell(r.name),
                        rx.table.cell(r.symbol),
                        rx.table.cell(r.market_cap_str),
                        rx.table.cell(r.pbr),
                        rx.table.cell(r.psr),
                        rx.table.cell(r.div_yield),
                        rx.table.cell(r.mfi),
                        rx.table.cell(r.close),
                        rx.table.cell(r.vwap_price),
                        rx.table.cell(r.vwap_gap),
                        rx.table.cell(
                            rx.badge(
                                r.condition,
                                color_scheme=rx.cond(
                                    r.condition == "원본", "green", "orange"
                                ),
                            )
                        ),
                        rx.table.cell(
                            rx.button(
                                "분석",
                                size="1",
                                variant="soft",
                                on_click=State.select_stock(r.name),
                            )
                        ),
                    ),
                )
            ),
                    width="100%",
                    variant="surface",
                ),
                ),
            ),
            ),
        ),
        ),  # rx.cond(trend)
        ),  # rx.cond(pullback)
        width="100%",
        spacing="4",
    )


def pmom_tab() -> rx.Component:
    """기간 모멘텀 전용 탭 — 3개월 슬라이딩 윈도우 캐시에서 즉시 로드."""
    def _period_btn(val: str, label: str):
        return rx.button(
            label,
            size="1",
            variant=rx.cond(State.pmom_period == val, "solid", "soft"),
            color_scheme="blue",
            on_click=State.set_pmom_period(val),
        )

    results_table = rx.vstack(
        # ── 캐시 정보 + 재스캔 버튼 ──────────────────────────────
        rx.hstack(
            rx.cond(
                State.pmom_from_cache,
                rx.text("캐시 기준 " + State.pmom_cache_time, size="1", color="gray"),
                rx.fragment(),
            ),
            rx.spacer(),
            rx.button(
                rx.icon("rotate-ccw", size=13), "재스캔",
                size="1", variant="soft", color_scheme="amber",
                loading=State.pmom_loading,
                on_click=State.do_load_pmom,
                title="유니버스 150종목 전체 재스캔",
            ),
            width="100%", align="center", spacing="2",
        ),
        # ── 결과 테이블 ──────────────────────────────────────────
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("순위"),
                    rx.table.column_header_cell("종목명"),
                    # col1: 정렬 기준 기간 (선택된 기간 → 굵게 강조)
                    rx.table.column_header_cell(
                        rx.text(State.pmom_col_labels[0], weight="bold", color="blue")
                    ),
                    rx.table.column_header_cell(State.pmom_col_labels[1]),
                    rx.table.column_header_cell(State.pmom_col_labels[2]),
                    rx.table.column_header_cell(State.pmom_col_labels[3]),
                    rx.table.column_header_cell("거래량비"),
                    rx.table.column_header_cell("현재가"),
                    rx.table.column_header_cell("시가총액"),
                    rx.table.column_header_cell(""),
                )
            ),
            rx.table.body(
                rx.foreach(
                    State.pmom_results,
                    lambda r: rx.table.row(
                        rx.table.cell(r["rank"]),
                        rx.table.cell(rx.text(r["name"], weight="medium")),
                        # col1: 선택된 기간 수익률 (굵게)
                        rx.table.cell(
                            rx.text(r["col1_str"],
                                color=rx.cond(r["col1_pos"], "green", "red"),
                                weight="bold")
                        ),
                        # col2~col4: 나머지 기간 수익률
                        rx.table.cell(
                            rx.text(r["col2_str"],
                                color=rx.cond(r["col2_pos"], "green", "red"),
                                size="1")
                        ),
                        rx.table.cell(
                            rx.text(r["col3_str"],
                                color=rx.cond(r["col3_pos"], "green", "red"),
                                size="1")
                        ),
                        rx.table.cell(
                            rx.text(r["col4_str"],
                                color=rx.cond(r["col4_pos"], "green", "red"),
                                size="1")
                        ),
                        rx.table.cell(
                            rx.badge(r["vol_ratio_str"],
                                color_scheme=rx.cond(r["vol_up"], "green", "gray"),
                                variant="soft", size="1")
                        ),
                        rx.table.cell(r["close_str"]),
                        rx.table.cell(r["mktcap_str"]),
                        rx.table.cell(
                            rx.button("조회", size="1", variant="soft", color_scheme="blue",
                                on_click=State.goto_lookup_from_leaders(r["code"], r["is_us"]))
                        ),
                    ),
                )
            ),
            variant="surface", width="100%",
        ),
        width="100%", spacing="2",
    )

    loading_view = rx.vstack(
        rx.hstack(
            rx.spinner(size="3"),
            rx.text(State.pmom_market + " 기간 모멘텀 스캔 중...", color="gray"),
            spacing="2", align="center",
        ),
        rx.cond(
            State.pmom_scan_progress != "",
            rx.text(State.pmom_scan_progress, size="2", color="blue", weight="medium"),
            rx.text("종목 데이터 수집 중...", size="1", color="gray"),
        ),
        align="center", spacing="2", padding_top="60px",
    )

    return rx.vstack(
        # ── 헤더: 시장 + 기간 선택 ───────────────────────────────
        rx.hstack(
            rx.heading("기간 모멘텀 TOP30", size="4"),
            rx.spacer(),
            # 시장 선택
            rx.hstack(
                rx.button("KOSPI", size="1",
                    variant=rx.cond(State.pmom_market == "KOSPI", "solid", "soft"),
                    color_scheme="violet",
                    on_click=State.set_pmom_market("KOSPI")),
                rx.button("KOSDAQ", size="1",
                    variant=rx.cond(State.pmom_market == "KOSDAQ", "solid", "soft"),
                    color_scheme="violet",
                    on_click=State.set_pmom_market("KOSDAQ")),
                rx.button("US", size="1",
                    variant=rx.cond(State.pmom_market == "SP500", "solid", "soft"),
                    color_scheme="violet",
                    on_click=State.set_pmom_market("SP500")),
                spacing="1",
            ),
            # 정렬 기준 선택
            rx.hstack(
                rx.text("정렬:", size="1", color="gray"),
                _period_btn("1W", "1주"),
                _period_btn("1M", "1개월"),
                _period_btn("2M", "2개월"),
                _period_btn("3M", "3개월"),
                spacing="1", align="center",
            ),
            width="100%", align="center", spacing="3", wrap="wrap",
        ),
        # ── 에러 메시지 ──────────────────────────────────────────
        rx.cond(
            State.pmom_error != "",
            rx.callout.root(
                rx.callout.icon(rx.icon("triangle-alert", size=16)),
                rx.callout.text(State.pmom_error),
                color_scheme="red", variant="soft",
            ),
            rx.fragment(),
        ),
        # ── 본문 ─────────────────────────────────────────────────
        rx.cond(
            State.pmom_loading,
            loading_view,
            rx.cond(
                State.pmom_results.length() > 0,
                results_table,
                rx.center(
                    rx.text("데이터를 불러오는 중입니다...", color="gray"),
                    height="200px",
                ),
            ),
        ),
        width="100%", spacing="3",
    )


def stock_momentum_table() -> rx.Component:
    """종목 모멘텀 스캔 결과 테이블."""
    warning_callout = rx.cond(
        State.scan_warning != "",
        rx.callout.root(
            rx.callout.icon(rx.icon("triangle-alert", size=16)),
            rx.callout.text(State.scan_warning),
            color_scheme="amber",
            variant="surface",
            width="100%",
            margin_bottom="2",
        ),
    )
    return rx.vstack(
        warning_callout,
        rx.cond(
            State.stock_momentum_results.length() == 0,
            rx.center(
                rx.text("위 패널에서 모멘텀 스캔을 실행하세요.", color="gray"),
                height="200px",
            ),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("순위"),
                        rx.table.column_header_cell("종목명"),
                        rx.table.column_header_cell("수익률"),
                        rx.table.column_header_cell("1주수익률"),
                        rx.table.column_header_cell("거래량비"),
                        rx.table.column_header_cell("현재가"),
                        rx.table.column_header_cell("시가총액"),
                        rx.table.column_header_cell(""),
                    )
                ),
                rx.table.body(
                    rx.foreach(
                        State.stock_momentum_results,
                        lambda r: rx.table.row(
                            rx.table.cell(r["rank"]),
                            rx.table.cell(rx.text(r["name"], weight="medium")),
                            rx.table.cell(
                                rx.text(r["ret_str"], color=rx.cond(r["ret_positive"], "green", "red"), weight="medium")
                            ),
                            rx.table.cell(
                                rx.cond(
                                    r["has_ret_1w"],
                                    rx.text(r["ret_1w_str"], color=rx.cond(r["ret_1w_positive"], "green", "red"), size="1"),
                                    rx.text("-", color="gray", size="1"),
                                )
                            ),
                            rx.table.cell(
                                rx.badge(r["vol_ratio_str"], color_scheme=rx.cond(r["vol_up"], "green", "gray"), variant="soft", size="1")
                            ),
                            rx.table.cell(r["close_str"]),
                            rx.table.cell(r["mktcap_str"]),
                            rx.table.cell(
                                rx.button(
                                    "조회", size="1", variant="soft", color_scheme="blue",
                                    on_click=State.goto_lookup_from_leaders(r["code"], r["is_us"]),
                                )
                            ),
                        ),
                    )
                ),
                variant="surface",
                width="100%",
            ),
        ),
        width="100%",
        spacing="0",
    )


def pullback_scanner_table() -> rx.Component:
    """눌림목 스캔 결과 테이블."""
    return rx.cond(
        State.pullback_results.length() == 0,
        rx.center(
            rx.vstack(
                rx.text("위 패널에서 눌림목 스캔을 실행하세요.", color="gray"),
                rx.text("KOSPI · KOSDAQ · SP500 지원 (시총 상위 150종목)", size="1", color="gray"),
                align="center", spacing="1",
            ),
            height="200px",
        ),
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("순위"),
                    rx.table.column_header_cell("종목명"),
                    rx.table.column_header_cell("1W낙폭"),
                    rx.table.column_header_cell("1M수익"),
                    rx.table.column_header_cell("3M수익"),
                    rx.table.column_header_cell("SMA60괴리"),
                    rx.table.column_header_cell("고점낙폭"),
                    rx.table.column_header_cell("RSI14"),
                    rx.table.column_header_cell("거래량비"),
                    rx.table.column_header_cell("현재가"),
                    rx.table.column_header_cell("시총"),
                    rx.table.column_header_cell(""),
                )
            ),
            rx.table.body(
                rx.foreach(
                    State.pullback_results,
                    lambda r: rx.table.row(
                        rx.table.cell(r["rank"]),
                        rx.table.cell(rx.text(r["name"], weight="medium")),
                        # 1W 낙폭 — 항상 음수, 빨간색
                        rx.table.cell(
                            rx.badge(r["ret_1w_str"], color_scheme="red",
                                     variant="soft", size="1")
                        ),
                        # 1M 수익
                        rx.table.cell(
                            rx.text(r["ret_1m_str"],
                                color=rx.cond(r["ret_1m_pos"], "green", "red"),
                                size="1")
                        ),
                        # 3M 수익 (굵게 — 정렬 기준)
                        rx.table.cell(
                            rx.text(r["ret_3m_str"],
                                color=rx.cond(r["ret_3m_pos"], "green", "red"),
                                weight="bold")
                        ),
                        # SMA60 괴리 (양수 = 추세선 위)
                        rx.table.cell(
                            rx.text(r["sma60_gap_str"], color="blue", size="1")
                        ),
                        # 20일 고점 낙폭
                        rx.table.cell(
                            rx.badge(
                                r["drawdown_str"],
                                color_scheme=rx.cond(r["drawdown_shallow"], "amber", "red"),
                                variant="soft", size="1",
                            )
                        ),
                        # RSI14 — 강한 과매도는 강조
                        rx.table.cell(
                            rx.badge(
                                r["rsi_str"],
                                color_scheme=rx.cond(r["rsi_strong"], "red", "amber"),
                                variant="soft", size="1",
                            )
                        ),
                        # 거래량비
                        rx.table.cell(
                            rx.badge(r["vol_ratio_str"],
                                color_scheme=rx.cond(r["vol_up"], "green", "gray"),
                                variant="soft", size="1")
                        ),
                        rx.table.cell(r["close_str"]),
                        rx.table.cell(r["mktcap_str"]),
                        rx.table.cell(
                            rx.button("조회", size="1", variant="soft", color_scheme="blue",
                                on_click=State.goto_lookup_from_leaders(r["code"], r["is_us"]))
                        ),
                    ),
                )
            ),
            variant="surface", width="100%",
        ),
    )


def _trend_detail_panel() -> rx.Component:
    """보유기간별 EV 상세 패널"""
    return rx.cond(
        State.trend_detail_code != "",
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.text("보유기간별 EV 분석", weight="bold", size="3"),
                    rx.text("·", color="gray"),
                    rx.text(State.trend_detail_code, color="gray", size="2"),
                    rx.text(State.trend_detail_entry_label, color="blue", size="2"),
                    rx.spacer(),
                    rx.cond(
                        State.trend_detail_loading,
                        rx.spinner(size="2"),
                        rx.text(""),
                    ),
                    align="center", width="100%",
                ),
                rx.cond(
                    State.trend_detail_loading,
                    rx.center(rx.text("계산 중...", color="gray"), height="80px"),
                    rx.cond(
                        State.trend_detail_rows.length() == 0,
                        rx.center(rx.text("데이터 없음", color="gray"), height="80px"),
                        rx.table.root(
                            rx.table.header(
                                rx.table.row(
                                    rx.table.column_header_cell("보유기간"),
                                    rx.table.column_header_cell("EV"),
                                    rx.table.column_header_cell("승률"),
                                    rx.table.column_header_cell("평균이익"),
                                    rx.table.column_header_cell("평균손실"),
                                    rx.table.column_header_cell("손익비"),
                                    rx.table.column_header_cell("표본"),
                                )
                            ),
                            rx.table.body(
                                rx.foreach(
                                    State.trend_detail_rows,
                                    lambda d: rx.table.row(
                                        rx.table.cell(
                                            rx.text(d["period_label"], weight="medium")
                                        ),
                                        rx.table.cell(
                                            rx.cond(
                                                d["has_data"],
                                                rx.text(
                                                    d["ev_str"],
                                                    color=rx.cond(d["ev_high"], "green",
                                                           rx.cond(d["ev_positive"], "blue", "red")),
                                                    weight=rx.cond(d["ev_high"], "bold", "regular"),
                                                ),
                                                rx.text("-", color="gray"),
                                            )
                                        ),
                                        rx.table.cell(
                                            rx.cond(
                                                d["has_data"],
                                                rx.text(
                                                    d["win_rate_str"],
                                                    color=rx.cond(d["win_rate_high"], "green", "gray"),
                                                    size="1",
                                                ),
                                                rx.text("-", color="gray", size="1"),
                                            )
                                        ),
                                        rx.table.cell(rx.text(d["avg_profit_str"], color="green", size="1")),
                                        rx.table.cell(rx.text(d["avg_loss_str"],   color="red",   size="1")),
                                        rx.table.cell(rx.text(d["pl_ratio_str"],               size="1")),
                                        rx.table.cell(rx.text(d["sample_n_str"],   color="gray", size="1")),
                                    ),
                                )
                            ),
                            variant="surface", width="100%",
                        ),
                    ),
                ),
                spacing="2", width="100%",
            ),
            border="1px solid var(--gray-5)",
            border_radius="8px",
            padding="16px",
            margin_top="12px",
            background="var(--gray-1)",
        ),
    )


def _season_panel() -> rx.Component:
    """12개월 계절성 EV 패널"""
    return rx.cond(
        State.season_code != "",
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.text("계절성 전략 분석", weight="bold", size="3"),
                    rx.text("·", color="gray"),
                    rx.text(State.season_code, color="gray", size="2"),
                    rx.text(State.season_entry_label, color="violet", size="2"),
                    rx.spacer(),
                    rx.hstack(
                        rx.text("보유기간:", size="1", color="gray"),
                        rx.button(
                            "5일",  size="1",
                            variant=rx.cond(State.season_hold_days == 5,  "solid", "soft"),
                            on_click=State.set_season_hold_days(5),
                        ),
                        rx.button(
                            "10일", size="1",
                            variant=rx.cond(State.season_hold_days == 10, "solid", "soft"),
                            on_click=State.set_season_hold_days(10),
                        ),
                        rx.button(
                            "20일", size="1",
                            variant=rx.cond(State.season_hold_days == 20, "solid", "soft"),
                            on_click=State.set_season_hold_days(20),
                        ),
                        rx.button(
                            "60일", size="1",
                            variant=rx.cond(State.season_hold_days == 60, "solid", "soft"),
                            on_click=State.set_season_hold_days(60),
                        ),
                        spacing="1",
                    ),
                    rx.cond(
                        State.season_loading,
                        rx.spinner(size="2"),
                        rx.text(""),
                    ),
                    align="center", width="100%",
                ),
                rx.cond(
                    State.season_loading,
                    rx.center(rx.text("계산 중...", color="gray"), height="80px"),
                    rx.cond(
                        State.season_rows.length() == 0,
                        rx.center(rx.text("데이터 없음", color="gray"), height="80px"),
                        rx.table.root(
                            rx.table.header(
                                rx.table.row(
                                    rx.table.column_header_cell("월"),
                                    rx.table.column_header_cell("EV"),
                                    rx.table.column_header_cell("승률"),
                                    rx.table.column_header_cell("평균이익"),
                                    rx.table.column_header_cell("평균손실"),
                                    rx.table.column_header_cell("손익비"),
                                    rx.table.column_header_cell("표본"),
                                )
                            ),
                            rx.table.body(
                                rx.foreach(
                                    State.season_rows,
                                    lambda d: rx.table.row(
                                        rx.table.cell(rx.text(d["month_kr"], weight="medium")),
                                        rx.table.cell(
                                            rx.cond(
                                                d["has_data"],
                                                rx.text(
                                                    d["ev_str"],
                                                    color=rx.cond(
                                                        d["ev_high"], "green",
                                                        rx.cond(d["ev_positive"], "blue", "red"),
                                                    ),
                                                    weight=rx.cond(d["ev_high"], "bold", "regular"),
                                                ),
                                                rx.text("-", color="gray"),
                                            )
                                        ),
                                        rx.table.cell(
                                            rx.cond(
                                                d["has_data"],
                                                rx.text(
                                                    d["win_rate_str"],
                                                    color=rx.cond(d["win_rate_high"], "green", "gray"),
                                                    size="1",
                                                ),
                                                rx.text("-", color="gray", size="1"),
                                            )
                                        ),
                                        rx.table.cell(rx.text(d["avg_profit_str"], color="green", size="1")),
                                        rx.table.cell(rx.text(d["avg_loss_str"],   color="red",   size="1")),
                                        rx.table.cell(rx.text(d["pl_ratio_str"],               size="1")),
                                        rx.table.cell(rx.text(d["sample_n_str"],   color="gray", size="1")),
                                    ),
                                )
                            ),
                            variant="surface", width="100%",
                        ),
                    ),
                ),
                spacing="2", width="100%",
            ),
            border="1px solid var(--violet-5)",
            border_radius="8px",
            padding="16px",
            margin_top="12px",
            background="var(--violet-1)",
        ),
    )


def trend_scanner_table() -> rx.Component:
    """추세추종 스캔 결과 테이블 — EV 순위."""
    return rx.cond(
        State.trend_results.length() == 0,
        rx.center(
            rx.vstack(
                rx.text("위 패널에서 추세추종 스캔을 실행하세요.", color="gray"),
                rx.text("RS90+ 강세 종목 × EMA눌림목·신고가돌파·박스권돌파 신호 × EV 순위", size="1", color="gray"),
                align="center", spacing="1",
            ),
            height="200px",
        ),
        rx.vstack(
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("순위"),
                        rx.table.column_header_cell("종목명"),
                        rx.table.column_header_cell("진입 신호"),
                        rx.table.column_header_cell("RS점수"),
                        rx.table.column_header_cell("EV(60일)"),
                        rx.table.column_header_cell("승률"),
                        rx.table.column_header_cell("손익비"),
                        rx.table.column_header_cell("평균이익"),
                        rx.table.column_header_cell("평균손실"),
                        rx.table.column_header_cell("표본"),
                        rx.table.column_header_cell("현재가"),
                        rx.table.column_header_cell(""),
                    )
                ),
                rx.table.body(
                    rx.foreach(
                        State.trend_results,
                        lambda r: rx.table.row(
                            rx.table.cell(r["rank"]),
                            rx.table.cell(rx.text(r["name"], weight="medium")),
                            rx.table.cell(
                                rx.badge(
                                    r["entry_label"],
                                    color_scheme=rx.cond(r["is_pullback"], "blue", "orange"),
                                    variant="soft", size="1",
                                )
                            ),
                            rx.table.cell(
                                rx.badge(
                                    r["rs_score_str"],
                                    color_scheme=rx.cond(r["rs_high"], "green", "gray"),
                                    variant="soft", size="1",
                                )
                            ),
                            rx.table.cell(
                                rx.text(
                                    r["ev_str"],
                                    color=rx.cond(r["ev_high"], "green", "gray"),
                                    weight=rx.cond(r["ev_high"], "bold", "regular"),
                                )
                            ),
                            rx.table.cell(rx.text(r["win_rate_str"], size="1")),
                            rx.table.cell(rx.text(r["pl_ratio_str"], size="1")),
                            rx.table.cell(rx.text(r["avg_profit_str"], color="green", size="1")),
                            rx.table.cell(rx.text(r["avg_loss_str"],   color="red",   size="1")),
                            rx.table.cell(rx.text(r["sample_n_str"],   color="gray",  size="1")),
                            rx.table.cell(r["close_str"]),
                            rx.table.cell(
                                rx.hstack(
                                    rx.button(
                                        "상세", size="1", variant="soft", color_scheme="violet",
                                        on_click=State.load_trend_detail(
                                            r["code"], r["entry_type"], r["ma_period"], r["entry_label"]
                                        )
                                    ),
                                    rx.button(
                                        "계절성", size="1", variant="soft", color_scheme="indigo",
                                        on_click=State.load_seasonality(
                                            r["code"], r["entry_type"], r["ma_period"], r["entry_label"]
                                        )
                                    ),
                                    rx.button(
                                        "분석", size="1", variant="soft", color_scheme="blue",
                                        on_click=State.goto_analysis(r["code"], r["name"], r["is_us"])
                                    ),
                                    spacing="1",
                                )
                            ),
                        ),
                    )
                ),
                variant="surface", width="100%",
            ),
            _trend_detail_panel(),
            _season_panel(),
            spacing="0", width="100%",
        ),
    )


def defensive_scanner_table() -> rx.Component:
    """하락장 방어 스캔 결과 테이블."""
    return rx.cond(
        State.defensive_results.length() == 0,
        rx.center(
            rx.text("위 패널에서 하락방어 스캔을 실행하세요. (KOSPI/KOSDAQ)", color="gray"),
            height="200px",
        ),
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("순위"),
                    rx.table.column_header_cell("종목명"),
                    rx.table.column_header_cell("시가총액"),
                    rx.table.column_header_cell("Beta"),
                    rx.table.column_header_cell("RS"),
                    rx.table.column_header_cell("하락포착률"),
                    rx.table.column_header_cell("하락일상승%"),
                    rx.table.column_header_cell("당일"),
                    rx.table.column_header_cell("5일"),
                    rx.table.column_header_cell("현재가"),
                    rx.table.column_header_cell(""),
                )
            ),
            rx.table.body(
                rx.foreach(
                    State.defensive_results,
                    lambda r: rx.table.row(
                        rx.table.cell(r["rank"]),
                        rx.table.cell(r["name"]),
                        rx.table.cell(r["mktcap_str"]),
                        rx.table.cell(r["beta_str"]),
                        rx.table.cell(
                            rx.badge(
                                r["rs_str"],
                                color_scheme=rx.cond(r["rs_positive"], "green", "gray"),
                                variant="soft",
                            )
                        ),
                        rx.table.cell(
                            rx.badge(
                                r["dc_str"],
                                color_scheme=rx.cond(r["dc_good"], "green", "orange"),
                                variant="soft",
                            )
                        ),
                        rx.table.cell(r["up_str"]),
                        rx.table.cell(
                            rx.text(
                                r["today_chg_str"],
                                color=rx.cond(r["today_chg_positive"], "green", "red"),
                                size="2",
                            )
                        ),
                        rx.table.cell(
                            rx.text(
                                r["five_day_chg_str"],
                                color=rx.cond(r["five_day_chg_positive"], "green", "red"),
                                size="2",
                            )
                        ),
                        rx.table.cell(r["close_str"]),
                        rx.table.cell(
                            rx.button(
                                "분석",
                                size="1",
                                variant="soft",
                                on_click=State.goto_lookup_from_leaders(r["code"], False),
                            )
                        ),
                    ),
                )
            ),
            width="100%",
            variant="surface",
        ),
    )


def whale_scanner_table() -> rx.Component:
    """세력 탐지 스캔 결과 테이블."""
    return rx.cond(
        State.whale_results.length() == 0,
        rx.center(
            rx.text("위 패널에서 세력 탐지 스캔을 실행하세요.", color="gray"),
            height="200px",
        ),
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("종목명"),
                    rx.table.column_header_cell("심볼"),
                    rx.table.column_header_cell("시그널일"),
                    rx.table.column_header_cell("점수"),
                    rx.table.column_header_cell("시그널 타입"),
                    rx.table.column_header_cell("매집봉"),
                    rx.table.column_header_cell("돌파"),
                    rx.table.column_header_cell("알파"),
                    rx.table.column_header_cell("숏커버"),
                    rx.table.column_header_cell("현재가"),
                    rx.table.column_header_cell("거래량 비율"),
                    rx.table.column_header_cell("적용 단계"),
                    rx.table.column_header_cell(""),
                )
            ),
            rx.table.body(
                rx.foreach(
                    State.whale_results,
                    lambda r: rx.table.row(
                        rx.table.cell(r.name),
                        rx.table.cell(r.symbol),
                        rx.table.cell(r.signal_date),
                        rx.table.cell(
                            rx.badge(
                                r.score,
                                color_scheme=rx.cond(r.score >= 100, "green", "orange"),
                            )
                        ),
                        rx.table.cell(
                            rx.cond(
                                r.signal_type != "-",
                                rx.badge(r.signal_type, color_scheme="blue"),
                                rx.text("-", color="gray"),
                            )
                        ),
                        rx.table.cell(
                            rx.cond(r.obv_spike, rx.badge("✓", color_scheme="green"), rx.text("-", color="gray"))
                        ),
                        rx.table.cell(
                            rx.cond(r.breakout, rx.badge("✓", color_scheme="amber"), rx.text("-", color="gray"))
                        ),
                        rx.table.cell(
                            rx.cond(r.alpha, rx.badge("✓", color_scheme="blue"), rx.text("-", color="gray"))
                        ),
                        rx.table.cell(
                            rx.cond(r.short_cover, rx.badge("✓", color_scheme="violet"), rx.text("-", color="gray"))
                        ),
                        rx.table.cell(r.close),
                        rx.table.cell(r.volume_ratio),
                        rx.table.cell(
                            rx.badge(
                                r.applied_step,
                                color_scheme=rx.cond(
                                    r.applied_step == "원본", "green", "orange"
                                ),
                                variant="soft",
                            )
                        ),
                        rx.table.cell(
                            rx.button(
                                "분석",
                                size="1",
                                variant="soft",
                                on_click=State.select_stock(r.name),
                            )
                        ),
                    ),
                )
            ),
            width="100%",
            variant="surface",
        ),
    )


def threshold_badge(label: str, value: rx.Component, ok: bool) -> rx.Component:
    return rx.hstack(
        rx.text(label, size="1", color="gray", width="80px"),
        rx.badge(value, color_scheme=rx.cond(ok, "green", "orange")),
        align_items="center",
        spacing="2",
    )


def scan_conditions_panel(r: ScanResult) -> rx.Component:
    """적용된 스캔 조건 패널."""
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text("적용된 스캔 조건", weight="bold", size="2"),
                rx.badge(r.condition, color_scheme=rx.cond(
                    r.condition == "원본", "blue", "orange"
                )),
                spacing="2",
                align_items="center",
            ),
            rx.grid(
                threshold_badge("PBR 한도", rx.text("≤ ", r.applied_pbr), r.applied_pbr <= 1.2),
                threshold_badge("GPA 최소", rx.text("≥ ", r.applied_gpa * 100, "%"), r.applied_gpa >= 0.6),
                threshold_badge("MFI 최소", rx.text("> ", r.applied_mfi), r.applied_mfi >= 50),
                threshold_badge("OBV 조건", rx.cond(r.applied_obv, rx.text("필수"), rx.text("제외")), r.applied_obv),
                threshold_badge("시가총액", rx.text(r.applied_min_cap), r.applied_min_cap == "전체"),
                columns="2",
                spacing="2",
                width="100%",
            ),
            spacing="3",
            width="100%",
        ),
        padding="16px",
        border_radius="8px",
        background="var(--gray-2)",
        border="1px solid var(--gray-5)",
        width="100%",
    )


def actual_values_panel(r: ScanResult) -> rx.Component:
    """실제 측정값 패널."""
    return rx.box(
        rx.vstack(
            rx.text("실제 측정값", weight="bold", size="2"),
            rx.grid(
                threshold_badge("PBR", rx.text(r.pbr), r.pbr <= r.applied_pbr),
                threshold_badge("MFI", rx.text(r.mfi), r.mfi > r.applied_mfi),
                threshold_badge("VWAP 괴리", rx.text(r.vwap_gap, "%"), r.vwap_gap > 0),
                threshold_badge("OBV", rx.cond(r.obv_ok, rx.text("충족"), rx.text("미충족")), r.obv_ok),
                threshold_badge("시가총액", rx.text(r.market_cap_str), True),
                columns="2",
                spacing="2",
                width="100%",
            ),
            spacing="3",
            width="100%",
        ),
        padding="16px",
        border_radius="8px",
        background="var(--gray-2)",
        border="1px solid var(--gray-5)",
        width="100%",
    )


def price_chart() -> rx.Component:
    """종가 + VWAP 라인 차트."""
    return rx.cond(
        State.is_loading_chart,
        rx.box(
            rx.center(rx.spinner(size="3"), height="200px"),
            padding="16px",
            border_radius="8px",
            background="var(--gray-2)",
            border="1px solid var(--gray-5)",
            width="100%",
        ),
        rx.cond(
            State.price_chart_data.length() > 0,
            rx.box(
                rx.vstack(
                    rx.hstack(
                        rx.text("가격 차트", weight="bold", size="2"),
                        rx.badge("종가", color_scheme="blue"),
                        rx.badge("VWAP " + State.vwap_period + "일", color_scheme="amber"),
                        rx.badge("TWAP20", color_scheme="green"),
                        rx.badge("TWAP60", color_scheme="red"),
                        rx.badge("TWAP120", color_scheme="purple"),
                        rx.badge("SMA120", color_scheme="orange"),
                        spacing="2",
                        align_items="center",
                    ),
                    rx.recharts.composed_chart(
                        rx.recharts.line(
                            data_key="종가",
                            stroke="#2563eb",
                            dot=False,
                            type_="monotone",
                            name="종가",
                            stroke_width=2,
                        ),
                        rx.recharts.line(
                            data_key="VWAP",
                            stroke="#f59e0b",
                            dot=False,
                            type_="monotone",
                            stroke_dasharray="6 3",
                            name="VWAP",
                            stroke_width=2,
                        ),
                        rx.recharts.line(
                            data_key="MA20",
                            stroke="#16a34a",
                            dot=False,
                            type_="monotone",
                            name="TWAP20",
                            stroke_width=1,
                        ),
                        rx.recharts.line(
                            data_key="MA60",
                            stroke="#dc2626",
                            dot=False,
                            type_="monotone",
                            name="TWAP60",
                            stroke_width=1,
                        ),
                        rx.recharts.line(
                            data_key="MA120",
                            stroke="#7c3aed",
                            dot=False,
                            type_="monotone",
                            name="TWAP120",
                            stroke_width=1,
                        ),
                        rx.recharts.line(
                            data_key="SMA120",
                            stroke="#ea580c",
                            dot=False,
                            type_="monotone",
                            name="SMA120",
                            stroke_width=1,
                            stroke_dasharray="4 2",
                        ),
                        rx.foreach(
                            State.whale_highlights,
                            lambda h: rx.recharts.reference_area(
                                x1=h["x1"],
                                x2=h["x2"],
                                fill="#f59e0b",
                                fill_opacity=0.15,
                                stroke="none",
                            ),
                        ),
                        rx.recharts.x_axis(data_key="date", tick={"fontSize": 9}),
                        rx.recharts.y_axis(tick={"fontSize": 9}),
                        rx.recharts.cartesian_grid(stroke_dasharray="3 3"),
                        rx.recharts.tooltip(),
                        rx.recharts.legend(),
                        data=State.price_chart_data,
                        width="100%",
                        height=320,
                    ),
                    width="100%",
                    spacing="3",
                ),
                padding="16px",
                border_radius="8px",
                background="var(--gray-2)",
                border="1px solid var(--gray-5)",
                width="100%",
            ),
            rx.box(),
        ),
    )


def bt_price_chart() -> rx.Component:
    """백테스트 가격 차트 — 가격선 + ReferenceDot 매수▲/매도▽ 마커."""
    return rx.cond(
        State.bt_price_chart_data.length() > 0,
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.text("가격 차트", weight="bold", size="2"),
                    rx.badge("종가", color_scheme="blue"),
                    rx.badge("VWAP " + State.vwap_period + "일", color_scheme="amber"),
                    rx.badge("TWAP20", color_scheme="green"),
                    rx.badge("TWAP60", color_scheme="red"),
                    rx.badge("TWAP120", color_scheme="purple"),
                    rx.badge("SMA120", color_scheme="orange"),
                    rx.badge("▲ 매수", color_scheme="grass"),
                    rx.badge("▽ 매도", color_scheme="tomato"),
                    spacing="2",
                    align_items="center",
                    flex_wrap="wrap",
                ),
                rx.recharts.composed_chart(
                    rx.recharts.line(
                        data_key="종가",
                        stroke="#2563eb",
                        dot=False,
                        type_="monotone",
                        name="종가",
                        stroke_width=2,
                    ),
                    rx.recharts.line(
                        data_key="VWAP",
                        stroke="#f59e0b",
                        dot=False,
                        type_="monotone",
                        stroke_dasharray="6 3",
                        name="VWAP",
                        stroke_width=2,
                    ),
                    rx.recharts.line(
                        data_key="MA20",
                        stroke="#16a34a",
                        dot=False,
                        type_="monotone",
                        name="TWAP20",
                        stroke_width=1,
                    ),
                    rx.recharts.line(
                        data_key="MA60",
                        stroke="#dc2626",
                        dot=False,
                        type_="monotone",
                        name="TWAP60",
                        stroke_width=1,
                    ),
                    rx.recharts.line(
                        data_key="MA120",
                        stroke="#7c3aed",
                        dot=False,
                        type_="monotone",
                        name="TWAP120",
                        stroke_width=1,
                    ),
                    rx.recharts.line(
                        data_key="SMA120",
                        stroke="#ea580c",
                        dot=False,
                        type_="monotone",
                        name="SMA120",
                        stroke_width=1,
                        stroke_dasharray="4 2",
                    ),
                    # 매수 마커: 초록 점 + ▲ 라벨
                    rx.foreach(
                        State.bt_buy_points,
                        lambda p: rx.recharts.reference_dot(
                            x=p["date"],
                            y=p["가격"],
                            r=7,
                            fill="#16a34a",
                            stroke="#ffffff",
                            stroke_width=2,
                            label="▲",
                        ),
                    ),
                    # 매도 마커: 빨간 점 + ▽ 라벨
                    rx.foreach(
                        State.bt_sell_points,
                        lambda p: rx.recharts.reference_dot(
                            x=p["date"],
                            y=p["가격"],
                            r=7,
                            fill="#dc2626",
                            stroke="#ffffff",
                            stroke_width=2,
                            label="▽",
                        ),
                    ),
                    rx.recharts.x_axis(data_key="date", tick={"fontSize": 9}),
                    rx.recharts.y_axis(tick={"fontSize": 9}),
                    rx.recharts.cartesian_grid(stroke_dasharray="3 3"),
                    rx.recharts.tooltip(),
                    rx.recharts.legend(),
                    data=State.bt_price_chart_data,
                    width="100%",
                    height=340,
                ),
                width="100%",
                spacing="3",
            ),
            padding="16px",
            border_radius="8px",
            background="var(--gray-2)",
            border="1px solid var(--gray-5)",
            width="100%",
        ),
    )


def buy_plan_panel() -> rx.Component:
    """분할 매수 플랜 패널."""
    return rx.box(
        rx.vstack(
            # 헤더
            rx.hstack(
                rx.text("분할 매수 플랜", weight="bold", size="3"),
                rx.cond(
                    State.plan_type != "",
                    rx.badge(State.plan_type, color_scheme="indigo"),
                ),
                spacing="3",
                align_items="center",
            ),
            # 예산 입력 + 계산 버튼
            rx.hstack(
                rx.text("투자 예산", size="2", color="gray", width="70px"),
                rx.input(
                    value=State.budget_input,
                    on_change=State.set_budget_input,
                    placeholder="예: 10000000",
                    type="number",
                    width="200px",
                ),
                rx.button(
                    "계산하기",
                    on_click=State.calc_buy_plan,
                    color_scheme="indigo",
                    size="2",
                ),
                spacing="3",
                align_items="center",
            ),
            # 플랜 테이블
            rx.cond(
                State.buy_plan_steps.length() > 0,
                rx.vstack(
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                rx.table.column_header_cell("매수 단계"),
                                rx.table.column_header_cell("목표 단가"),
                                rx.table.column_header_cell("비중"),
                                rx.table.column_header_cell("배정 금액"),
                                rx.table.column_header_cell("예상 수량"),
                            )
                        ),
                        rx.table.body(
                            rx.foreach(
                                State.buy_plan_steps,
                                lambda s: rx.table.row(
                                    rx.table.cell(rx.text(s.level, size="2")),
                                    rx.table.cell(rx.text(s.price)),
                                    rx.table.cell(rx.badge(rx.text(s.weight_pct, "%"), color_scheme="blue")),
                                    rx.table.cell(rx.text(s.amount)),
                                    rx.table.cell(rx.text(s.shares, "주")),
                                ),
                            )
                        ),
                        variant="surface",
                        width="100%",
                    ),
                    # 요약 정보
                    rx.grid(
                        rx.box(
                            rx.text("예상 평균 단가", size="1", color="gray"),
                            rx.text(State.plan_avg_price, weight="bold", size="4", color="blue"),
                            padding="12px",
                            border_radius="6px",
                            background="var(--blue-2)",
                            border="1px solid var(--blue-4)",
                        ),
                        rx.box(
                            rx.text("손절 가격 (VWAP -4%)", size="1", color="gray"),
                            rx.hstack(
                                rx.text(State.plan_stop_loss, weight="bold", size="4", color="red"),
                                rx.badge(rx.text(State.plan_stop_loss_pct, "%"), color_scheme="red"),
                                spacing="2",
                                align_items="center",
                            ),
                            padding="12px",
                            border_radius="6px",
                            background="var(--red-2)",
                            border="1px solid var(--red-4)",
                        ),
                        columns="2",
                        spacing="3",
                        width="100%",
                    ),
                    width="100%",
                    spacing="3",
                ),
            ),
            spacing="4",
            width="100%",
        ),
        padding="16px",
        border_radius="8px",
        background="var(--indigo-2)",
        border="1px solid var(--indigo-5)",
        width="100%",
    )


def psr_chart() -> rx.Component:
    """분기별 PSR 추이 바 차트."""
    return rx.cond(
        State.psr_chart_data.length() > 0,
        rx.vstack(
            rx.hstack(
                rx.text("분기별 PSR 추이", weight="bold", size="2"),
                rx.badge("PSR = 시가총액 ÷ 매출액", color_scheme="gray"),
                spacing="2",
                align_items="center",
            ),
            rx.recharts.bar_chart(
                rx.recharts.bar(
                    data_key="PSR",
                    fill="#6366f1",
                    name="PSR",
                    radius=[4, 4, 0, 0],
                ),
                rx.recharts.x_axis(data_key="quarter", tick={"fontSize": 10}),
                rx.recharts.y_axis(tick={"fontSize": 10}),
                rx.recharts.cartesian_grid(stroke_dasharray="3 3"),
                rx.recharts.tooltip(),
                rx.recharts.reference_line(
                    y=1,
                    stroke="#ef4444",
                    stroke_dasharray="4 4",
                    label="PSR=1",
                ),
                data=State.psr_chart_data,
                width="100%",
                height=240,
            ),
            rx.text(
                "PSR < 1 → 매출 대비 저평가 / PSR 1~3 → 적정 / PSR > 3 → 고평가 주의",
                size="1", color="gray",
            ),
            width="100%",
        ),
        rx.box(),
    )


def whale_chart_panel() -> rx.Component:
    """세력 탐지 보조 차트: OBV + 공매도 잔고."""
    return rx.cond(
        State.whale_chart_data.length() > 0,
        rx.vstack(
            # OBV 차트
            rx.box(
                rx.vstack(
                    rx.hstack(
                        rx.text("OBV (On-Balance Volume)", weight="bold", size="2"),
                        rx.badge("매집 강도", color_scheme="violet"),
                        spacing="2",
                        align_items="center",
                    ),
                    rx.recharts.line_chart(
                        rx.recharts.line(
                            data_key="OBV",
                            stroke="#7c3aed",
                            dot=False,
                            type_="monotone",
                            stroke_width=2,
                            name="OBV",
                        ),
                        rx.recharts.x_axis(data_key="date", tick={"fontSize": 9}),
                        rx.recharts.y_axis(tick={"fontSize": 9}),
                        rx.recharts.cartesian_grid(stroke_dasharray="3 3"),
                        rx.recharts.tooltip(),
                        data=State.whale_chart_data,
                        width="100%",
                        height=200,
                    ),
                    width="100%",
                    spacing="2",
                ),
                padding="16px",
                border_radius="8px",
                background="var(--violet-2)",
                border="1px solid var(--violet-5)",
                width="100%",
            ),
            # 공매도 잔고 차트 (US만 데이터 있음)
            rx.cond(
                State.whale_chart_data.length() > 0,
                rx.box(
                    rx.vstack(
                        rx.hstack(
                            rx.text("공매도 잔고 추이", weight="bold", size="2"),
                            rx.badge("Short Balance", color_scheme="red"),
                            rx.badge("미국 시장만", color_scheme="gray", variant="soft"),
                            spacing="2",
                            align_items="center",
                        ),
                        rx.recharts.line_chart(
                            rx.recharts.line(
                                data_key="Short_Balance",
                                stroke="#ef4444",
                                dot=False,
                                type_="monotone",
                                stroke_width=2,
                                name="공매도 잔고",
                            ),
                            rx.recharts.x_axis(data_key="date", tick={"fontSize": 9}),
                            rx.recharts.y_axis(tick={"fontSize": 9}),
                            rx.recharts.cartesian_grid(stroke_dasharray="3 3"),
                            rx.recharts.tooltip(),
                            data=State.whale_chart_data,
                            width="100%",
                            height=180,
                        ),
                        width="100%",
                        spacing="2",
                    ),
                    padding="16px",
                    border_radius="8px",
                    background="var(--red-2)",
                    border="1px solid var(--red-5)",
                    width="100%",
                ),
            ),
            width="100%",
            spacing="3",
        ),
        rx.box(),
    )


def analysis_tab() -> rx.Component:
    return rx.cond(
        State.selected_name != "",
        rx.box(
            rx.vstack(
                # 상단 헤더 (종목명 + 기준일 + PDF 버튼)
                rx.hstack(
                    rx.heading(State.selected_name, size="5"),
                    rx.cond(
                        State.close_date != "",
                        rx.badge(
                            "종가 기준: " + State.close_date,
                            color_scheme="gray",
                            variant="soft",
                        ),
                    ),
                    rx.spacer(),
                    rx.button(
                        rx.cond(
                            State.show_add_holding_form,
                            "취소",
                            "+ 보유 추가",
                        ),
                        on_click=State.toggle_add_holding_form,
                        color_scheme=rx.cond(State.show_add_holding_form, "gray", "green"),
                        variant="soft",
                        size="2",
                        class_name="no-print",
                    ),
                    rx.button(
                        "PDF 저장",
                        on_click=State.export_pdf,
                        color_scheme="gray",
                        variant="soft",
                        size="2",
                        class_name="no-print",
                    ),
                    width="100%",
                    align_items="center",
                    spacing="3",
                ),
                # 보유 종목 정보 (보유종목 탭에서 분석 클릭 시 표시)
                rx.cond(
                    State.selected_is_holding,
                    rx.box(
                        rx.hstack(
                            rx.badge("보유중", color_scheme="green", variant="solid", size="1"),
                            rx.cond(
                                State.selected_holding_buy_price > 0,
                                rx.text(
                                    "매수가: ",
                                    rx.text.span(
                                        State.selected_holding_buy_price.to_string(),
                                        weight="bold",
                                    ),
                                    size="2",
                                ),
                            ),
                            rx.cond(
                                State.selected_holding_quantity > 0,
                                rx.text(
                                    "수량: ",
                                    rx.text.span(
                                        State.selected_holding_quantity.to_string(),
                                        weight="bold",
                                    ),
                                    size="2",
                                ),
                            ),
                            rx.cond(
                                State.selected_holding_memo != "",
                                rx.text(
                                    "메모: ",
                                    rx.text.span(State.selected_holding_memo, weight="bold"),
                                    size="2",
                                ),
                            ),
                            spacing="4",
                            align_items="center",
                            flex_wrap="wrap",
                        ),
                        padding="10px 16px",
                        border_radius="8px",
                        background="var(--green-2)",
                        border="1px solid var(--green-6)",
                        width="100%",
                        class_name="no-print",
                    ),
                ),
                # 보유 추가 폼 — rx.cond 대신 display로 토글 (이벤트 핸들러 등록 보장)
                rx.box(
                    rx.vstack(
                        rx.text("보유 종목 등록", weight="bold", size="2"),
                        rx.hstack(
                            rx.vstack(
                                rx.text("매수가", size="1", color="gray"),
                                rx.input(
                                    placeholder="예) 45000",
                                    value=State.holding_buy_price_input,
                                    on_change=State.set_holding_buy_price_input,
                                    size="2",
                                    width="140px",
                                ),
                                spacing="1",
                            ),
                            rx.vstack(
                                rx.text("수량", size="1", color="gray"),
                                rx.input(
                                    placeholder="예) 100",
                                    value=State.holding_quantity_input,
                                    on_change=State.set_holding_quantity_input,
                                    size="2",
                                    width="100px",
                                ),
                                spacing="1",
                            ),
                            rx.vstack(
                                rx.text("메모", size="1", color="gray"),
                                rx.input(
                                    placeholder="선택 입력",
                                    value=State.holding_memo_input,
                                    on_change=State.set_holding_memo_input,
                                    size="2",
                                    width="200px",
                                ),
                                spacing="1",
                            ),
                            rx.button(
                                "등록",
                                on_click=State.add_to_holdings,
                                color_scheme="green",
                                size="2",
                            ),
                            align_items="flex-end",
                            spacing="3",
                            flex_wrap="wrap",
                        ),
                        rx.cond(
                            State.holding_status == "already",
                            rx.callout.root(
                                rx.callout.text("이미 보유 목록에 등록된 종목입니다."),
                                color_scheme="orange", variant="soft", size="1",
                            ),
                        ),
                        rx.cond(
                            State.holding_status == "added",
                            rx.callout.root(
                                rx.callout.text("보유 목록에 추가됐습니다."),
                                color_scheme="green", variant="soft", size="1",
                            ),
                        ),
                        rx.cond(
                            State.holding_status == "debug",
                            rx.callout.root(
                                rx.callout.text(State.holding_status),
                                color_scheme="red", variant="soft", size="1",
                            ),
                        ),
                        spacing="3",
                    ),
                    padding="16px",
                    border_radius="8px",
                    background="var(--green-2)",
                    border="1px solid var(--green-6)",
                    width="100%",
                    class_name="no-print",
                    display=rx.cond(State.show_add_holding_form, "block", "none"),
                ),
                # 퀀트 모드: 매수 근거 / 분할 매수 플랜 / 지표 가이드 / 매도 가이드
                rx.cond(
                    State.scan_mode == "quant",
                    rx.vstack(
                        rx.box(
                            rx.text("매수 근거", weight="bold", color="green", size="2"),
                            rx.text(State.buy_msg, size="2"),
                            padding="16px",
                            border_radius="8px",
                            background="var(--green-2)",
                            border="1px solid var(--green-6)",
                            width="100%",
                        ),
                        buy_plan_panel(),
                        rx.box(
                            rx.vstack(
                                rx.text("지표 해석 가이드", weight="bold", size="2", color="blue"),
                                rx.grid(
                                    rx.vstack(
                                        rx.hstack(
                                            rx.badge("MFI", color_scheme="blue"),
                                            rx.text("Money Flow Index", size="2", weight="bold"),
                                            spacing="2",
                                        ),
                                        rx.text(
                                            "거래량을 반영한 0~100 범위의 수급 강도 지표. "
                                            "50 초과 → 매수 우위(스마트 머니 유입), "
                                            "80 이상 → 과매수 주의, "
                                            "20 이하 → 과매도 반등 가능성.",
                                            size="1", color="gray",
                                        ),
                                        align_items="start", spacing="1",
                                    ),
                                    rx.vstack(
                                        rx.hstack(
                                            rx.badge("OBV", color_scheme="violet"),
                                            rx.text("On-Balance Volume", size="2", weight="bold"),
                                            spacing="2",
                                        ),
                                        rx.text(
                                            "누적 거래량으로 자금 흐름 방향을 측정. "
                                            "OBV > OBV신호선(20일MA) → 매수세 우위, "
                                            "주가 상승 + OBV 상승 → 추세 신뢰도 높음, "
                                            "주가 상승 + OBV 하락 → 다이버전스 경고.",
                                            size="1", color="gray",
                                        ),
                                        align_items="start", spacing="1",
                                    ),
                                    columns="2",
                                    spacing="4",
                                    width="100%",
                                ),
                                spacing="3",
                                width="100%",
                            ),
                            padding="16px",
                            border_radius="8px",
                            background="var(--blue-2)",
                            border="1px solid var(--blue-5)",
                            width="100%",
                        ),
                        rx.box(
                            rx.text("매도 가이드", weight="bold", color="red", size="2"),
                            rx.text(State.sell_msg, size="2"),
                            padding="16px",
                            border_radius="8px",
                            background="var(--red-2)",
                            border="1px solid var(--red-6)",
                            width="100%",
                        ),
                        width="100%",
                        spacing="4",
                    ),
                    # 세력 탐지 모드: 시그널 요약 박스
                    rx.box(
                        rx.vstack(
                            rx.hstack(
                                rx.badge("세력 매집 탐지", color_scheme="amber"),
                                rx.text("매집 구간은 가격 차트에 황금색 음영으로 표시됩니다.", size="2", color="gray"),
                                spacing="2",
                                align_items="center",
                            ),
                            rx.text(
                                "OBV 급증(30pt) + 지수 대비 알파(35pt) + 공매도 잔고 급감(35pt) 합산 점수 ≥ 70 기준",
                                size="1", color="gray",
                            ),
                            spacing="2",
                            width="100%",
                        ),
                        padding="16px",
                        border_radius="8px",
                        background="var(--amber-2)",
                        border="1px solid var(--amber-5)",
                        width="100%",
                    ),
                ),
                # 가격 차트 (공통)
                price_chart(),
                # 세력 탐지 보조 차트 (OBV + 공매도 잔고)
                rx.cond(
                    State.scan_mode == "whale",
                    whale_chart_panel(),
                ),
                # 분기별 PSR 추이 (퀀트 모드만)
                rx.cond(
                    State.scan_mode == "quant",
                    psr_chart(),
                ),
                # 적용된 스캔 조건 / 실제 측정값 (퀀트 모드만)
                rx.cond(
                    State.scan_mode == "quant",
                    rx.foreach(
                        State.scan_results,
                        lambda r: rx.cond(
                            r.name == State.selected_name,
                            rx.vstack(
                                scan_conditions_panel(r),
                                actual_values_panel(r),
                                width="100%",
                                spacing="3",
                            ),
                            rx.box(),
                        ),
                    ),
                ),
                rx.button(
                    rx.cond(State.is_backtesting, rx.spinner(size="2"), rx.text("백테스트 실행")),
                    on_click=State.run_backtest,
                    disabled=State.is_backtesting,
                    color_scheme="violet",
                    class_name="no-print",
                ),
                backtest_tab(),
                width="100%",
                spacing="4",
            ),
            id="analysis-print-area",
            width="100%",
        ),
        rx.center(
            rx.text("스캔 결과에서 종목을 선택하세요.", color="gray"),
            height="150px",
        ),
    )


def metric_card(label: str, value: rx.Component, color: str) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.text(label, size="1", color="gray"),
            rx.text(value, size="6", weight="bold", color=color),
            align_items="start",
            spacing="1",
        ),
    )


def backtest_strategy_info() -> rx.Component:
    """백테스트 전략 설명 카드."""
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.icon("trending-up", size=16, color="var(--accent-9)"),
                rx.text("VWAP 돌파 전략", weight="bold", size="3"),
                align="center",
                spacing="2",
            ),
            rx.separator(width="100%"),
            rx.grid(
                rx.vstack(
                    rx.text("진입 조건", size="2", weight="bold", color="green"),
                    rx.text("• 종가 > VWAP", size="2"),
                    rx.text("• MFI > 50 (자금 유입 우세)", size="2"),
                    rx.text("• OBV > OBV 신호선 (거래량 확인)", size="2"),
                    align_items="start",
                    spacing="1",
                ),
                rx.vstack(
                    rx.text("청산 조건", size="2", weight="bold", color="red"),
                    rx.text("• 종가 < VWAP (추세 이탈)", size="2"),
                    rx.text("• 미청산 포지션은 기간 말 강제 청산", size="2"),
                    align_items="start",
                    spacing="1",
                ),
                rx.vstack(
                    rx.text("기본 설정", size="2", weight="bold", color="blue"),
                    rx.text("• 초기 자본: 1,000만 원", size="2"),
                    rx.text(
                        rx.hstack(
                            rx.text("• VWAP 기간: ", size="2"),
                            rx.text(State.vwap_period, size="2"),
                            rx.text("일", size="2"),
                            spacing="0",
                        )
                    ),
                    rx.text("• 조회 기간: 최근 600 거래일", size="2"),
                    align_items="start",
                    spacing="1",
                ),
                columns="3",
                spacing="4",
                width="100%",
            ),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        padding="16px",
        border_radius="8px",
        border="1px solid var(--gray-4)",
        background="var(--gray-1)",
        width="100%",
    )


def backtest_tab() -> rx.Component:
    s = State.bt_summary
    return rx.cond(
        State.bt_summary.trade_count > 0,
        rx.vstack(
            backtest_strategy_info(),
            rx.heading("백테스트 결과", size="5"),
            rx.grid(
                metric_card(
                    "총 수익률",
                    rx.text(s.total_return, "%"),
                    rx.cond(s.total_return >= 0, "green", "red"),
                ),
                metric_card(
                    "최대 낙폭(MDD)",
                    rx.text(s.mdd, "%"),
                    rx.cond(s.mdd > -20, "green", "red"),
                ),
                metric_card(
                    "승률",
                    rx.text(s.win_rate, "%"),
                    rx.cond(s.win_rate >= 50, "green", "red"),
                ),
                metric_card(
                    "평균 수익률",
                    rx.text(s.avg_return, "%"),
                    rx.cond(s.avg_return >= 0, "green", "red"),
                ),
                metric_card(
                    "샤프 지수",
                    rx.text(s.sharpe),
                    rx.cond(s.sharpe >= 1, "green", "orange"),
                ),
                metric_card(
                    "총 거래 수",
                    rx.text(s.trade_count, "회"),
                    "blue",
                ),
                columns="3",
                spacing="4",
                width="100%",
            ),
            bt_price_chart(),
            rx.cond(
                State.equity_data.length() > 0,
                rx.vstack(
                    rx.heading("자본금 추이", size="4"),
                    rx.recharts.line_chart(
                        rx.recharts.line(
                            data_key="value",
                            stroke="#3b82f6",
                            dot=False,
                            type_="monotone",
                        ),
                        rx.recharts.x_axis(data_key="date"),
                        rx.recharts.y_axis(),
                        rx.recharts.cartesian_grid(stroke_dasharray="3 3"),
                        rx.recharts.tooltip(),
                        data=State.equity_data,
                        width="100%",
                        height=300,
                    ),
                    width="100%",
                ),
            ),
            rx.cond(
                State.trades_data.length() > 0,
                rx.vstack(
                    rx.heading("매매 내역", size="4"),
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                rx.table.column_header_cell("진입일"),
                                rx.table.column_header_cell("청산일"),
                                rx.table.column_header_cell("진입가"),
                                rx.table.column_header_cell("청산가"),
                                rx.table.column_header_cell("수익률(%)"),
                                rx.table.column_header_cell("손익(원)"),
                            )
                        ),
                        rx.table.body(
                            rx.foreach(
                                State.trades_data,
                                lambda t: rx.table.row(
                                    rx.table.cell(t["Entry"]),
                                    rx.table.cell(t["Exit"]),
                                    rx.table.cell(t["Entry_Price"]),
                                    rx.table.cell(t["Exit_Price"]),
                                    rx.table.cell(t["Return"]),
                                    rx.table.cell(t["PnL"]),
                                ),
                            )
                        ),
                        variant="surface",
                        width="100%",
                    ),
                    width="100%",
                    overflow_x="auto",
                ),
            ),
            width="100%",
            spacing="5",
        ),
        rx.fragment(),
    )


def history_tab() -> rx.Component:
    """저장된 스캔 결과 히스토리 탭."""
    return rx.vstack(
        rx.heading("스캔 히스토리", size="4"),
        # 저장된 스캔 선택
        rx.cond(
            State.saved_runs.length() == 0,
            rx.callout.root(
                rx.callout.text("저장된 스캔 결과가 없습니다. 스캔 후 '결과 저장' 버튼을 누르세요."),
                color_scheme="gray",
                variant="soft",
            ),
            rx.vstack(
                rx.select.root(
                    rx.select.trigger(placeholder="날짜 / 시장 / 조건 선택"),
                    rx.select.content(
                        rx.foreach(
                            State.saved_runs,
                            lambda r: rx.select.item(r.label, value=r.run_id),
                        ),
                    ),
                    value=State.selected_run_id,
                    on_change=State.set_selected_run_id,
                    width="100%",
                ),
                # 결과 테이블 — 퀀트 / 세력탐지 분기
                rx.cond(
                    State.selected_run_mode == "whale",
                    # 세력 탐지 히스토리
                    rx.cond(
                        State.history_whale_results.length() > 0,
                        rx.table.root(
                            rx.table.header(
                                rx.table.row(
                                    rx.table.column_header_cell("종목명"),
                                    rx.table.column_header_cell("심볼"),
                                    rx.table.column_header_cell("시장"),
                                    rx.table.column_header_cell("시그널일"),
                                    rx.table.column_header_cell("점수"),
                                    rx.table.column_header_cell("시그널"),
                                    rx.table.column_header_cell("현재가"),
                                    rx.table.column_header_cell("거래량비율"),
                                    rx.table.column_header_cell("적용단계"),
                                    rx.table.column_header_cell(""),
                                )
                            ),
                            rx.table.body(
                                rx.foreach(
                                    State.history_whale_results,
                                    lambda r: rx.table.row(
                                        rx.table.cell(r.name),
                                        rx.table.cell(r.symbol),
                                        rx.table.cell(r.market),
                                        rx.table.cell(r.signal_date),
                                        rx.table.cell(rx.badge(r.score, color_scheme="blue")),
                                        rx.table.cell(r.signal_type),
                                        rx.table.cell(r.close),
                                        rx.table.cell(r.volume_ratio),
                                        rx.table.cell(
                                            rx.badge(
                                                r.applied_step,
                                                color_scheme=rx.cond(
                                                    r.applied_step == "원본", "green", "orange"
                                                ),
                                            )
                                        ),
                                        rx.table.cell(
                                            rx.button(
                                                "분석",
                                                size="1",
                                                variant="soft",
                                                on_click=State.select_stock(r.name),
                                            )
                                        ),
                                    ),
                                )
                            ),
                            width="100%",
                            variant="surface",
                        ),
                        rx.center(
                            rx.text("날짜를 선택하면 결과가 표시됩니다.", color="gray"),
                            height="100px",
                        ),
                    ),
                    # 퀀트 히스토리
                    rx.cond(
                        State.history_results.length() > 0,
                        rx.table.root(
                            rx.table.header(
                                rx.table.row(
                                    rx.table.column_header_cell("종목명"),
                                    rx.table.column_header_cell("심볼"),
                                    rx.table.column_header_cell("시가총액"),
                                    rx.table.column_header_cell("PBR"),
                                    rx.table.column_header_cell("PSR"),
                                    rx.table.column_header_cell("배당률"),
                                    rx.table.column_header_cell("MFI"),
                                    rx.table.column_header_cell("현재가"),
                                    rx.table.column_header_cell("VWAP"),
                                    rx.table.column_header_cell("괴리율(%)"),
                                    rx.table.column_header_cell("조건"),
                                    rx.table.column_header_cell(""),
                                )
                            ),
                            rx.table.body(
                                rx.foreach(
                                    State.history_results,
                                    lambda r: rx.table.row(
                                        rx.table.cell(r.name),
                                        rx.table.cell(r.symbol),
                                        rx.table.cell(r.market_cap_str),
                                        rx.table.cell(r.pbr),
                                        rx.table.cell(r.psr),
                                        rx.table.cell(r.div_yield),
                                        rx.table.cell(r.mfi),
                                        rx.table.cell(r.close),
                                        rx.table.cell(r.vwap_price),
                                        rx.table.cell(r.vwap_gap),
                                        rx.table.cell(
                                            rx.badge(
                                                r.condition,
                                                color_scheme=rx.cond(
                                                    r.condition == "원본", "green", "orange"
                                                ),
                                            )
                                        ),
                                        rx.table.cell(
                                            rx.button(
                                                "분석",
                                                size="1",
                                                variant="soft",
                                                on_click=State.select_stock(r.name),
                                            )
                                        ),
                                    ),
                                )
                            ),
                            width="100%",
                            variant="surface",
                        ),
                        rx.center(
                            rx.text("날짜를 선택하면 결과가 표시됩니다.", color="gray"),
                            height="100px",
                        ),
                    ),
                ),
                width="100%",
                spacing="4",
            ),
        ),
        width="100%",
        spacing="4",
    )


def holdings_tab() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.heading("보유 종목", size="4"),
            rx.spacer(),
            rx.text(
                State.holdings.length(),
                "개 종목",
                size="2",
                color="gray",
            ),
            width="100%",
            align_items="center",
        ),
        rx.cond(
            State.holdings.length() == 0,
            rx.callout.root(
                rx.callout.text("등록된 보유 종목이 없습니다. 분석 탭에서 '+ 보유 추가' 버튼을 누르세요."),
                color_scheme="gray",
                variant="soft",
            ),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("종목명"),
                        rx.table.column_header_cell("시장"),
                        rx.table.column_header_cell("현재가"),
                        rx.table.column_header_cell("VWAP"),
                        rx.table.column_header_cell("괴리율(%)"),
                        rx.table.column_header_cell("MFI"),
                        rx.table.column_header_cell("PBR"),
                        rx.table.column_header_cell("매수가"),
                        rx.table.column_header_cell("수량"),
                        rx.table.column_header_cell("메모"),
                        rx.table.column_header_cell("등록일"),
                        rx.table.column_header_cell(""),
                    )
                ),
                rx.table.body(
                    rx.foreach(
                        State.holdings,
                        lambda h: rx.table.row(
                            rx.table.cell(h.name),
                            rx.table.cell(
                                rx.badge(
                                    h.market,
                                    color_scheme=rx.cond(
                                        (h.market == "SP500") | (h.market == "NASDAQ") | (h.market == "US-ETF"),
                                        "blue",
                                        "green",
                                    ),
                                    variant="soft",
                                )
                            ),
                            rx.table.cell(h.close),
                            rx.table.cell(h.vwap_price),
                            rx.table.cell(h.vwap_gap),
                            rx.table.cell(h.mfi),
                            rx.table.cell(h.pbr),
                            rx.table.cell(
                                rx.cond(h.buy_price > 0, h.buy_price, rx.text("-", color="gray"))
                            ),
                            rx.table.cell(
                                rx.cond(h.quantity > 0, h.quantity, rx.text("-", color="gray"))
                            ),
                            rx.table.cell(
                                rx.cond(h.memo != "", h.memo, rx.text("-", color="gray"))
                            ),
                            rx.table.cell(h.added_at),
                            rx.table.cell(
                                rx.hstack(
                                    rx.button(
                                        "분석",
                                        size="1",
                                        variant="soft",
                                        color_scheme="blue",
                                        on_click=State.select_holding_for_analysis(h.holding_id),
                                    ),
                                    rx.button(
                                        "삭제",
                                        size="1",
                                        variant="soft",
                                        color_scheme="red",
                                        on_click=State.remove_holding(h.holding_id),
                                    ),
                                    spacing="2",
                                )
                            ),
                        ),
                    )
                ),
                variant="surface",
                width="100%",
            ),
        ),
        width="100%",
        spacing="4",
    )


def _momentum_strategy_card(
    title: str, subtitle: str,
    rec_name: rx.Component, rec_desc: rx.Component,
    is_cash: rx.Component, detail_id: str,
) -> rx.Component:
    """전략 추천 카드 (클릭 시 하단 상세 테이블 전환)."""
    selected = State.momentum_detail == detail_id
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text(title, size="2", weight="bold"),
                rx.cond(selected, rx.badge("선택", size="1", color_scheme="blue"), rx.fragment()),
                justify="between",
                width="100%",
            ),
            rx.text(subtitle, size="1", color="gray"),
            rx.divider(),
            rx.text("추천", size="1", color="gray"),
            rx.text(rec_name, size="3", weight="bold"),
            rx.badge(rec_desc, size="1", color_scheme=rx.cond(is_cash, "gray", "green"), variant="soft"),
            spacing="2",
            align_items="start",
            width="100%",
        ),
        padding="16px",
        border_radius="10px",
        border=rx.cond(selected, "2px solid var(--blue-8)", "1px solid var(--gray-4)"),
        background=rx.cond(selected, "var(--blue-2)", "var(--gray-1)"),
        cursor="pointer",
        on_click=State.set_momentum_detail(detail_id),
        width="100%",
        _hover={"border": "2px solid var(--blue-6)"},
    )


def momentum_tab() -> rx.Component:
    """글로벌 시장 모멘텀 전략 탭 — 4가지 전략 비교."""

    # ── 공통 헬퍼 ──────────────────────────────────────────────
    def ret_badge(ret_str, win_flag, pos_flag):
        return rx.badge(
            ret_str,
            color_scheme=rx.cond(win_flag, "green", rx.cond(pos_flag, "teal", "red")),
            variant=rx.cond(win_flag, "solid", "soft"),
        )

    def name_cell(r, rec_flag):
        return rx.table.cell(
            rx.hstack(
                rx.cond(rec_flag, rx.badge("★", color_scheme="gold", size="1"), rx.fragment()),
                rx.text(r["name"], weight=rx.cond(rec_flag, "bold", "regular"), size="2"),
                spacing="2", align="center",
            )
        )

    # ── 단순 모멘텀 상세 테이블 ───────────────────────────────
    def momentum_row(r):
        return rx.table.row(
            name_cell(r, r["is_rec_momentum"]),
            rx.cond(State.momentum_show_1m,
                rx.table.cell(ret_badge(r["ret_1m_str"], r["win_1m"], r["pos_1m"])),
                rx.fragment()),
            rx.cond(State.momentum_show_3m,
                rx.table.cell(ret_badge(r["ret_3m_str"], r["win_3m"], r["pos_3m"])),
                rx.fragment()),
            rx.cond(State.momentum_show_6m,
                rx.table.cell(ret_badge(r["ret_6m_str"], r["win_6m"], r["pos_6m"])),
                rx.fragment()),
            rx.cond(State.momentum_show_12m,
                rx.table.cell(ret_badge(r["ret_12m_str"], r["win_12m"], r["pos_12m"])),
                rx.fragment()),
        )

    momentum_table = rx.table.root(
        rx.table.header(rx.table.row(
            rx.table.column_header_cell("자산"),
            rx.cond(State.momentum_show_1m, rx.table.column_header_cell("1개월"), rx.fragment()),
            rx.cond(State.momentum_show_3m, rx.table.column_header_cell("3개월"), rx.fragment()),
            rx.cond(State.momentum_show_6m, rx.table.column_header_cell("6개월"), rx.fragment()),
            rx.cond(State.momentum_show_12m, rx.table.column_header_cell("12개월"), rx.fragment()),
        )),
        rx.table.body(rx.foreach(State.momentum_rows, momentum_row)),
        width="100%", variant="surface",
    )

    # ── VAA 상세 테이블 ────────────────────────────────────────
    def vaa_row(r):
        return rx.table.row(
            name_cell(r, r["is_rec_vaa"]),
            rx.table.cell(rx.badge(r["ret_1m_str"],
                color_scheme=rx.cond(r["pos_1m"], "teal", "red"), variant="soft")),
            rx.table.cell(rx.badge(r["ret_3m_str"],
                color_scheme=rx.cond(r["pos_3m"], "teal", "red"), variant="soft")),
            rx.table.cell(rx.badge(r["ret_6m_str"],
                color_scheme=rx.cond(r["pos_6m"], "teal", "red"), variant="soft")),
            rx.table.cell(rx.badge(r["ret_12m_str"],
                color_scheme=rx.cond(r["pos_12m"], "teal", "red"), variant="soft")),
            rx.table.cell(
                rx.badge(r["vaa_score_str"],
                    color_scheme=rx.cond(r["is_rec_vaa"], "green",
                        rx.cond(r["vaa_positive"], "teal", "red")),
                    variant=rx.cond(r["is_rec_vaa"], "solid", "soft"),
                    weight="bold",
                )
            ),
        )

    vaa_table = rx.vstack(
        rx.text("점수 = 12×1M + 4×3M + 2×6M + 1×12M  |  최고 점수 자산 선택, 음수면 현금",
            size="1", color="gray"),
        rx.table.root(
            rx.table.header(rx.table.row(
                rx.table.column_header_cell("자산"),
                rx.table.column_header_cell("1개월"),
                rx.table.column_header_cell("3개월"),
                rx.table.column_header_cell("6개월"),
                rx.table.column_header_cell("12개월"),
                rx.table.column_header_cell("VAA 점수"),
            )),
            rx.table.body(rx.foreach(State.momentum_rows, vaa_row)),
            width="100%", variant="surface",
        ),
        spacing="2", width="100%",
    )

    # ── MA200 상세 테이블 ──────────────────────────────────────
    def ma_row(r):
        return rx.table.row(
            name_cell(r, r["is_rec_ma"]),
            rx.table.cell(r["close_str"]),
            rx.table.cell(r["ma200_str"]),
            rx.table.cell(
                rx.badge(r["ma_signal_str"],
                    color_scheme=rx.cond(r["above_ma"], "green", "red"),
                    variant="soft",
                )
            ),
            rx.table.cell(
                rx.badge(r["ret_12m_str"],
                    color_scheme=rx.cond(r["pos_12m"], "teal", "red"),
                    variant=rx.cond(r["is_rec_ma"], "solid", "soft"),
                )
            ),
        )

    ma_table = rx.vstack(
        rx.text("현재가 > 200일 이동평균인 자산 중 12개월 수익률 1위 선택",
            size="1", color="gray"),
        rx.table.root(
            rx.table.header(rx.table.row(
                rx.table.column_header_cell("자산"),
                rx.table.column_header_cell("현재가"),
                rx.table.column_header_cell("MA200"),
                rx.table.column_header_cell("신호"),
                rx.table.column_header_cell("12개월"),
            )),
            rx.table.body(rx.foreach(State.momentum_rows, ma_row)),
            width="100%", variant="surface",
        ),
        spacing="2", width="100%",
    )

    # ── 역변동성 상세 테이블 ───────────────────────────────────
    def invvol_row(r):
        return rx.table.row(
            name_cell(r, r["is_rec_invvol"]),
            rx.table.cell(r["vol_str"]),
            rx.table.cell(
                rx.hstack(
                    rx.box(
                        background="var(--blue-8)",
                        height="10px",
                        width=r["inv_vol_weight_str"],
                        border_radius="3px",
                        min_width="4px",
                    ),
                    rx.text(r["inv_vol_weight_str"], size="2"),
                    spacing="2", align="center",
                )
            ),
        )

    invvol_table = rx.vstack(
        rx.text("변동성(60일 연환산) 역수에 비례하여 비중 배분 — 변동성 낮을수록 더 많이 투자",
            size="1", color="gray"),
        rx.table.root(
            rx.table.header(rx.table.row(
                rx.table.column_header_cell("자산"),
                rx.table.column_header_cell("변동성(연)"),
                rx.table.column_header_cell("배분 비중"),
            )),
            rx.table.body(rx.foreach(State.momentum_rows, invvol_row)),
            width="100%", variant="surface",
        ),
        spacing="2", width="100%",
    )

    # ── 탭 레이아웃 조합 ───────────────────────────────────────
    return rx.vstack(
        # 컨트롤 바
        rx.hstack(
            rx.text("기간 (단순모멘텀):", size="2", color="gray"),
            rx.button("1M", size="1",
                variant=rx.cond(State.momentum_show_1m, "solid", "soft"),
                color_scheme="gray", on_click=State.toggle_momentum_1m),
            rx.button("3M", size="1",
                variant=rx.cond(State.momentum_show_3m, "solid", "soft"),
                color_scheme="gray", on_click=State.toggle_momentum_3m),
            rx.button("6M", size="1",
                variant=rx.cond(State.momentum_show_6m, "solid", "soft"),
                color_scheme="gray", on_click=State.toggle_momentum_6m),
            rx.button("12M", size="1",
                variant=rx.cond(State.momentum_show_12m, "solid", "soft"),
                color_scheme="gray", on_click=State.toggle_momentum_12m),
            rx.spacer(),
            rx.button(
                rx.cond(
                    State.momentum_loading,
                    rx.hstack(rx.spinner(size="2"), rx.text("조회 중..."), spacing="2"),
                    rx.text("조회"),
                ),
                on_click=State.fetch_momentum,
                disabled=State.momentum_loading,
                color_scheme="blue",
            ),
            spacing="3", align="center", wrap="wrap", width="100%",
        ),
        # 오류
        rx.cond(
            State.momentum_error != "",
            rx.callout(State.momentum_error, color_scheme="red"),
        ),
        # 4개 전략 추천 카드
        rx.cond(
            State.momentum_rows.length() > 0,
            rx.grid(
                _momentum_strategy_card(
                    "단순 모멘텀", "3·6·12M 수익률 기반",
                    State.momentum_recommendation, State.momentum_rec_reason,
                    State.momentum_rec_key == "cash", "momentum",
                ),
                _momentum_strategy_card(
                    "VAA 모멘텀", "12×1M + 4×3M + 2×6M + 1×12M",
                    State.momentum_vaa_rec_name, State.momentum_vaa_rec_desc,
                    State.momentum_vaa_rec_key == "cash", "vaa",
                ),
                _momentum_strategy_card(
                    "MA200 필터", "200일 이동평균 위 자산 중 12M 1위",
                    State.momentum_ma_rec_name, State.momentum_ma_rec_desc,
                    State.momentum_ma_rec_key == "cash", "ma",
                ),
                _momentum_strategy_card(
                    "역변동성 배분", "변동성 역수 비례 비중",
                    "분산 배분", State.momentum_invvol_rec_desc,
                    False, "invvol",
                ),
                columns="2",
                gap="3",
                width="100%",
            ),
        ),
        # 상세 테이블 (카드 클릭으로 전환)
        rx.cond(
            State.momentum_rows.length() > 0,
            rx.box(
                rx.cond(State.momentum_detail == "momentum", momentum_table, rx.fragment()),
                rx.cond(State.momentum_detail == "vaa", vaa_table, rx.fragment()),
                rx.cond(State.momentum_detail == "ma", ma_table, rx.fragment()),
                rx.cond(State.momentum_detail == "invvol", invvol_table, rx.fragment()),
                width="100%",
            ),
        ),
        # ── 백테스트 섹션 ─────────────────────────────────────────
        rx.separator(width="100%"),
        rx.vstack(
            rx.heading("전략 백테스트 (월별 리밸런싱)", size="3"),
            rx.hstack(
                rx.text("기간:", size="2", color="gray"),
                rx.button("3년", size="1",
                    variant=rx.cond(State.momentum_bt_years == 3, "solid", "soft"),
                    color_scheme="gray", on_click=State.set_momentum_bt_years(3)),
                rx.button("5년", size="1",
                    variant=rx.cond(State.momentum_bt_years == 5, "solid", "soft"),
                    color_scheme="gray", on_click=State.set_momentum_bt_years(5)),
                rx.button("10년", size="1",
                    variant=rx.cond(State.momentum_bt_years == 10, "solid", "soft"),
                    color_scheme="gray", on_click=State.set_momentum_bt_years(10)),
                rx.button(
                    rx.cond(
                        State.momentum_bt_loading,
                        rx.hstack(rx.spinner(size="2"), rx.text("계산 중..."), spacing="2"),
                        rx.text("백테스트 실행"),
                    ),
                    on_click=State.run_momentum_backtest,
                    disabled=State.momentum_bt_loading,
                    color_scheme="blue",
                    size="1",
                ),
                spacing="2", align="center", wrap="wrap",
            ),
            rx.cond(
                State.momentum_bt_error != "",
                rx.callout(State.momentum_bt_error, color_scheme="red"),
            ),
            rx.cond(
                State.momentum_bt_chart.length() > 0,
                rx.vstack(
                    rx.box(
                        rx.recharts.composed_chart(
                            rx.recharts.line(data_key="momentum", stroke="#2563eb", dot=False,
                                type_="monotone", name="단순모멘텀", stroke_width=2),
                            rx.recharts.line(data_key="vaa", stroke="#16a34a", dot=False,
                                type_="monotone", name="VAA", stroke_width=2),
                            rx.recharts.line(data_key="ma200", stroke="#f59e0b", dot=False,
                                type_="monotone", name="MA200필터", stroke_width=2),
                            rx.recharts.line(data_key="invvol", stroke="#7c3aed", dot=False,
                                type_="monotone", name="역변동성", stroke_width=2),
                            rx.recharts.line(data_key="equal", stroke="#94a3b8", dot=False,
                                type_="monotone", name="균등분산", stroke_width=1,
                                stroke_dasharray="5 5"),
                            rx.recharts.x_axis(data_key="date", tick={"fontSize": 9}),
                            rx.recharts.y_axis(tick={"fontSize": 9}),
                            rx.recharts.cartesian_grid(stroke_dasharray="3 3"),
                            rx.recharts.tooltip(),
                            rx.recharts.legend(),
                            data=State.momentum_bt_chart,
                            width="100%",
                            height=320,
                        ),
                        width="100%",
                        padding="12px",
                        border_radius="8px",
                        background="var(--gray-2)",
                        border="1px solid var(--gray-5)",
                    ),
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                rx.table.column_header_cell("전략"),
                                rx.table.column_header_cell("총수익률"),
                                rx.table.column_header_cell("CAGR"),
                                rx.table.column_header_cell("MDD"),
                                rx.table.column_header_cell("Sharpe"),
                            )
                        ),
                        rx.table.body(
                            rx.foreach(
                                State.momentum_bt_summary,
                                lambda r: rx.table.row(
                                    rx.table.cell(
                                        rx.text(r["strategy"],
                                            weight=rx.cond(r["is_best"], "bold", "regular"),
                                            color=rx.cond(r["is_best"], "var(--blue-11)", "inherit"))
                                    ),
                                    rx.table.cell(r["total_ret"]),
                                    rx.table.cell(r["cagr"]),
                                    rx.table.cell(r["mdd"]),
                                    rx.table.cell(r["sharpe"]),
                                )
                            )
                        ),
                        width="100%",
                        size="1",
                    ),
                    spacing="3",
                    width="100%",
                ),
            ),
            spacing="3",
            width="100%",
        ),
        rx.text("※ 투자 조언이 아닙니다. 참고용으로만 활용하세요.", size="1", color="gray"),
        spacing="5",
        width="100%",
    )


def _ret_badge(ret_str, ret_positive, has_data) -> rx.Component:
    return rx.cond(
        has_data,
        rx.badge(
            ret_str,
            color_scheme=rx.cond(ret_positive, "green", "red"),
            variant="solid",
            size="2",
            min_width="80px",
            justify="center",
        ),
        rx.text("-", color="gray", size="2"),
    )


def _sector_col_header(label: str, period_key: str) -> rx.Component:
    """정렬 기준 컬럼은 파란색 + 화살표 표시."""
    return rx.table.column_header_cell(
        rx.hstack(
            rx.text(
                label,
                color=rx.cond(State.sector_sort_period == period_key, "var(--blue-11)", "inherit"),
                weight=rx.cond(State.sector_sort_period == period_key, "bold", "regular"),
                size="2",
            ),
            rx.cond(
                State.sector_sort_period == period_key,
                rx.text("▼", size="1", color="var(--blue-11)"),
                rx.fragment(),
            ),
            spacing="1", align="center",
        ),
        cursor="pointer",
        on_click=State.set_sector_sort_period(period_key),
    )


def sector_tab() -> rx.Component:
    return rx.vstack(
        # ── 컨트롤 바 ──────────────────────────────────────────────
        rx.hstack(
            rx.heading("섹터 모멘텀", size="4"),
            rx.spacer(),
            rx.hstack(
                rx.button("KR", size="1",
                    variant=rx.cond(State.sector_region == "KR", "solid", "soft"),
                    on_click=State.set_sector_region("KR")),
                rx.button("US", size="1",
                    variant=rx.cond(State.sector_region == "US", "solid", "soft"),
                    on_click=State.set_sector_region("US")),
                spacing="1",
            ),
            rx.button(
                rx.cond(State.sector_loading, rx.spinner(size="1"), rx.text("조회")),
                on_click=State.fetch_sector_momentum,
                disabled=State.sector_loading,
                size="1", color_scheme="blue",
            ),
            width="100%", align="center", spacing="3",
        ),
        # ── 기간 선택 (정렬 기준) ────────────────────────────────
        rx.hstack(
            rx.text("정렬 기준:", size="2", color="gray", weight="medium"),
            rx.button("5일",   size="1", color_scheme="blue",
                variant=rx.cond(State.sector_sort_period == "5d",  "solid", "soft"),
                on_click=State.set_sector_sort_period("5d")),
            rx.button("1개월", size="1", color_scheme="blue",
                variant=rx.cond(State.sector_sort_period == "1m",  "solid", "soft"),
                on_click=State.set_sector_sort_period("1m")),
            rx.button("3개월", size="1", color_scheme="blue",
                variant=rx.cond(State.sector_sort_period == "3m",  "solid", "soft"),
                on_click=State.set_sector_sort_period("3m")),
            rx.button("6개월", size="1", color_scheme="blue",
                variant=rx.cond(State.sector_sort_period == "6m",  "solid", "soft"),
                on_click=State.set_sector_sort_period("6m")),
            rx.button("12개월", size="1", color_scheme="blue",
                variant=rx.cond(State.sector_sort_period == "12m", "solid", "soft"),
                on_click=State.set_sector_sort_period("12m")),
            spacing="1", align="center",
        ),
        # ── 에러 ──────────────────────────────────────────────────
        rx.cond(
            State.sector_error != "",
            rx.callout.root(
                rx.callout.text(State.sector_error),
                color_scheme="red", variant="soft",
            ),
        ),
        # ── 테이블 / 안내 ─────────────────────────────────────────
        rx.cond(
            State.sector_data.length() > 0,
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("자산"),
                        _sector_col_header("5일",   "5d"),
                        _sector_col_header("1개월",  "1m"),
                        _sector_col_header("3개월",  "3m"),
                        _sector_col_header("6개월",  "6m"),
                        _sector_col_header("12개월", "12m"),
                    )
                ),
                rx.table.body(
                    rx.foreach(
                        State.sector_data,
                        lambda s: rx.table.row(
                            rx.table.cell(rx.text(s["label"], size="2")),
                            rx.table.cell(_ret_badge(s["ret_5d_str"],  s["ret_5d_positive"],  s["ret_5d_has_data"])),
                            rx.table.cell(_ret_badge(s["ret_1m_str"],  s["ret_1m_positive"],  s["ret_1m_has_data"])),
                            rx.table.cell(_ret_badge(s["ret_3m_str"],  s["ret_3m_positive"],  s["ret_3m_has_data"])),
                            rx.table.cell(_ret_badge(s["ret_6m_str"],  s["ret_6m_positive"],  s["ret_6m_has_data"])),
                            rx.table.cell(_ret_badge(s["ret_12m_str"], s["ret_12m_positive"], s["ret_12m_has_data"])),
                        ),
                    )
                ),
                variant="surface", width="100%",
            ),
            rx.cond(
                State.sector_loading,
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("섹터 데이터 조회 중...", color="gray"),
                    spacing="2", align="center", padding_top="40px",
                ),
                rx.callout.root(
                    rx.callout.text("KR / US 선택 후 조회 버튼을 눌러 섹터 수익률을 확인하세요."),
                    color_scheme="blue", variant="soft",
                ),
            ),
        ),
        spacing="4",
        width="100%",
    )


def leaders_tab() -> rx.Component:
    """당일 주도주 탭 — 방법A/B 복합 점수 정렬."""
    return rx.vstack(
        # ── 컨트롤 바 ──────────────────────────────────────────
        rx.hstack(
            rx.heading("당일 주도주", size="4"),
            rx.spacer(),
            rx.hstack(
                rx.button("KOSPI", size="1",
                    variant=rx.cond(State.leaders_market == "KOSPI", "solid", "soft"),
                    color_scheme="violet",
                    on_click=State.set_leaders_market("KOSPI")),
                rx.button("KOSDAQ", size="1",
                    variant=rx.cond(State.leaders_market == "KOSDAQ", "solid", "soft"),
                    color_scheme="violet",
                    on_click=State.set_leaders_market("KOSDAQ")),
                rx.button("US", size="1",
                    variant=rx.cond(State.leaders_market == "US", "solid", "soft"),
                    color_scheme="violet",
                    on_click=State.set_leaders_market("US")),
                spacing="1",
            ),
            rx.button(
                "조회",
                on_click=State.do_fetch_leaders,
                loading=State.leaders_loading,
                disabled=State.leaders_loading,
            ),
            width="100%",
            align_items="center",
            spacing="3",
        ),
        # ── 행1: 정렬 + B점수 계산 ───────────────────────────────
        rx.cond(
            State.leaders_data.length() > 0,
            rx.vstack(
                rx.hstack(
                    rx.text("정렬:", size="2", color="gray", weight="medium"),
                    rx.button("방법A", size="1", color_scheme="blue",
                        on_click=State.set_leaders_sort("방법A"),
                        variant=rx.cond(State.leaders_sort == "방법A", "solid", "soft")),
                    rx.button("방법B", size="1", color_scheme="blue",
                        on_click=State.set_leaders_sort("방법B"),
                        variant=rx.cond(State.leaders_sort == "방법B", "solid", "soft")),
                    rx.button("거래량", size="1", color_scheme="blue",
                        on_click=State.set_leaders_sort("거래량"),
                        variant=rx.cond(State.leaders_sort == "거래량", "solid", "soft")),
                    rx.button("상승률", size="1", color_scheme="blue",
                        on_click=State.set_leaders_sort("상승률"),
                        variant=rx.cond(State.leaders_sort == "상승률", "solid", "soft")),
                    rx.spacer(),
                    rx.button(
                        rx.cond(
                            State.leaders_b_loading, "계산 중...",
                            rx.cond(State.leaders_score_b_done, "B점수 재계산", "B점수 계산"),
                        ),
                        on_click=State.do_compute_score_b,
                        loading=State.leaders_b_loading,
                        disabled=State.leaders_b_loading,
                        variant="soft",
                        color_scheme=rx.cond(State.leaders_score_b_done, "green", "amber"),
                        size="1",
                    ),
                    width="100%", align_items="center", spacing="2",
                ),
                # ── 행2: 종류 필터 ──────────────────────────────────
                rx.hstack(
                    rx.text("종류:", size="2", color="gray", weight="medium"),
                    rx.button("전체", size="1", color_scheme="gray",
                        on_click=State.set_leaders_type_filter("전체"),
                        variant=rx.cond(State.leaders_type_filter == "전체", "solid", "soft")),
                    rx.button("ETF/ETN", size="1", color_scheme="orange",
                        on_click=State.set_leaders_type_filter("ETF"),
                        variant=rx.cond(State.leaders_type_filter == "ETF", "solid", "soft")),
                    rx.button("일반주", size="1", color_scheme="green",
                        on_click=State.set_leaders_type_filter("일반주"),
                        variant=rx.cond(State.leaders_type_filter == "일반주", "solid", "soft")),
                    width="100%", align_items="center", spacing="2",
                ),
                # ── 행3: 추가 필터 (독립 레벨) ──────────────────────
                rx.hstack(
                    rx.text("필터:", size="2", color="gray", weight="medium"),
                    rx.button(
                        "종가매매 후보",
                        on_click=State.toggle_leaders_close_buy,
                        variant=rx.cond(State.leaders_close_buy, "solid", "soft"),
                        color_scheme="tomato", size="1",
                    ),
                    width="100%", align_items="center", spacing="2",
                ),
                width="100%", spacing="1",
            ),
        ),
        # ── 점수 설명 ───────────────────────────────────────────
        rx.cond(
            State.leaders_data.length() > 0,
            rx.hstack(
                rx.badge("방법A = 1/거래량순위 + 1/상승률순위", color_scheme="blue", variant="soft"),
                rx.badge("방법B = (오늘거래량 ÷ 20일평균) × 상승률%", color_scheme="amber", variant="soft"),
                spacing="2",
            ),
        ),
        # ── 종가매매 필터 기준 안내 ──────────────────────────────
        rx.cond(
            State.leaders_close_buy,
            rx.callout.root(
                rx.callout.text(
                    rx.hstack(
                        rx.icon("triangle-alert", size=14),
                        rx.text(
                            "종가매매 후보 필터 적용 중 — "
                            "① 상승률 +5% 이상  "
                            "② 거래량 상위 + 상승률 상위 동시 등재  "
                            "③ 종가 ÷ 당일고가 ≥ 98% (고가 근처 마감)",
                            size="2",
                        ),
                        spacing="2",
                        align="center",
                    )
                ),
                color_scheme="tomato",
                variant="soft",
            ),
        ),
        # ── 캐시 알림 ───────────────────────────────────────────
        rx.cond(
            State.leaders_from_cache,
            rx.hstack(
                rx.badge(
                    "캐시 로드 (" + State.leaders_cache_time + ")",
                    color_scheme="green",
                    variant="soft",
                ),
                rx.text("오늘 11시 자동 조회 데이터입니다.", size="1", color="gray"),
                spacing="2",
                align="center",
            ),
        ),
        # ── 데이터 기준일 ─────────────────────────────────────────
        rx.cond(
            State.leaders_data_date != "",
            rx.hstack(
                rx.badge(
                    "데이터 기준: " + State.leaders_data_date,
                    color_scheme=rx.cond(State.leaders_data_is_prev, "amber", "green"),
                    variant="soft",
                    size="1",
                ),
                rx.cond(
                    State.leaders_data_is_prev,
                    rx.text("전일 종가 기준 데이터입니다.", size="1", color="gray"),
                    rx.text("당일 데이터입니다.", size="1", color="gray"),
                ),
                spacing="2",
                align="center",
            ),
        ),
        # ── 에러 ────────────────────────────────────────────────
        rx.cond(
            State.leaders_error != "",
            rx.callout.root(
                rx.callout.text(State.leaders_error),
                color_scheme="red",
                variant="soft",
            ),
        ),
        # ── 당일 주도주 뷰 ───────────────────────────────────────
        rx.cond(
            State.leaders_data.length() == 0,
            rx.cond(
                State.leaders_loading,
                rx.hstack(
                    rx.spinner(size="3"),
                    rx.text(State.leaders_market + " 거래량·상승률 상위 종목 조회 중...", color="gray"),
                    spacing="2",
                    align="center",
                    padding_top="40px",
                ),
                rx.cond(
                    State.leaders_data_raw.length() > 0,
                    rx.callout.root(
                        rx.callout.text("해당하는 후보가 없습니다."),
                        color_scheme="amber",
                        variant="soft",
                    ),
                    rx.callout.root(
                        rx.callout.text("'조회' 버튼을 눌러 오늘의 주도주를 가져오세요."),
                        color_scheme="blue",
                        variant="soft",
                    ),
                ),
            ),
            # ── 데이터 뷰 (모바일 카드 + 데스크탑 테이블) ────────
            rx.vstack(
                # ── Best Pick 카드 ──
                rx.cond(
                    State.leaders_best_pick.length() > 0,
                    rx.box(
                        rx.foreach(
                            State.leaders_best_pick,
                            lambda p: rx.hstack(
                                rx.vstack(
                                    rx.hstack(
                                        rx.icon("star", size=14, color="var(--amber-11)"),
                                        rx.text(
                                            "오늘의 Best Pick (일반주)",
                                            size="1", color="var(--amber-11)", weight="bold",
                                        ),
                                        spacing="1", align="center",
                                    ),
                                    rx.hstack(
                                        rx.text(p["name"], weight="bold", size="3"),
                                        rx.text(p["code"], size="1", color="gray"),
                                        spacing="2", align="center",
                                    ),
                                    rx.text(p["reason"], size="1", color="var(--gray-11)"),
                                    spacing="1",
                                ),
                                rx.spacer(),
                                rx.button(
                                    "분석",
                                    size="1",
                                    color_scheme="amber",
                                    variant="soft",
                                    on_click=State.goto_lookup_from_leaders(p["code"], p["is_us"]),
                                ),
                                align="center", width="100%",
                            ),
                        ),
                        background="var(--amber-2)",
                        border="1px solid var(--amber-5)",
                        border_radius="8px",
                        padding="12px 16px",
                        margin_bottom="8px",
                        width="100%",
                    ),
                    rx.fragment(),
                ),
                # 모바일 카드
                rx.box(
                    rx.foreach(
                        State.leaders_data,
                        lambda h: rx.card(
                        rx.vstack(
                            rx.hstack(
                                rx.badge(h["rank"], variant="soft", color_scheme="gray"),
                                rx.text(h["name"], weight="bold", size="3"),
                                rx.cond(
                                    h["has_streak"],
                                    rx.badge(
                                        h["consecutive_days"].to_string() + "일 연속",
                                        color_scheme=rx.cond(
                                            h["streak_hot"], "tomato", "amber"
                                        ),
                                        variant="solid", size="1",
                                    ),
                                    rx.fragment(),
                                ),
                                rx.spacer(),
                                rx.text(
                                    h["change_pct_str"],
                                    color=rx.cond(h["change_positive"], "green", "red"),
                                    weight="bold", size="3",
                                ),
                                width="100%", align="center",
                            ),
                            rx.hstack(
                                rx.vstack(
                                    rx.text("현재가", size="1", color="gray"),
                                    rx.text(h["price_str"], size="2", weight="medium"),
                                    spacing="0",
                                ),
                                rx.vstack(
                                    rx.text("시가총액", size="1", color="gray"),
                                    rx.text(h["mktcap_str"], size="2"),
                                    spacing="0",
                                ),
                                rx.vstack(
                                    rx.text("A점수", size="1", color="gray"),
                                    rx.text(h["score_a_str"], size="2", weight="medium"),
                                    spacing="0",
                                ),
                                rx.vstack(
                                    rx.text("B점수", size="1", color="gray"),
                                    rx.text(rx.cond(h["has_score_b"], h["score_b_str"], "-"), size="2"),
                                    spacing="0",
                                ),
                                justify="between", width="100%",
                            ),
                            rx.hstack(
                                rx.cond(h["has_vol_rank"],
                                    rx.badge(rx.text("거래량 ", h["vol_rank_str"]), color_scheme="blue", variant="soft", size="1"),
                                    rx.fragment(),
                                ),
                                rx.cond(h["has_rise_rank"],
                                    rx.badge(rx.text("상승률 ", h["rise_rank_str"]), color_scheme="green", variant="soft", size="1"),
                                    rx.fragment(),
                                ),
                                rx.spacer(),
                                rx.button("조회", size="1", variant="soft", color_scheme="blue",
                                    on_click=State.goto_lookup_from_leaders(h["code"], h["is_us"])),
                                width="100%", align="center", spacing="2",
                            ),
                            spacing="2", width="100%",
                        ),
                        width="100%",
                    ),
                ),
                    display=rx.breakpoints(initial="block", sm="block", md="none"),
                    width="100%",
                ),
                # 데스크탑 테이블
                rx.box(
                    rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("순위"),
                            rx.table.column_header_cell("종목명"),
                            rx.table.column_header_cell("시가총액"),
                            rx.table.column_header_cell("현재가"),
                            rx.table.column_header_cell("등락률"),
                            rx.table.column_header_cell("연속"),
                            rx.table.column_header_cell("거래량순위"),
                            rx.table.column_header_cell("상승률순위"),
                            rx.table.column_header_cell("A점수"),
                            rx.table.column_header_cell("B점수"),
                            rx.table.column_header_cell(""),
                        )
                    ),
                    rx.table.body(
                        rx.foreach(
                            State.leaders_data,
                            lambda h: rx.table.row(
                                rx.table.cell(h["rank"]),
                                rx.table.cell(rx.text(h["name"], weight="medium")),
                                rx.table.cell(h["mktcap_str"]),
                                rx.table.cell(h["price_str"]),
                                rx.table.cell(
                                    rx.text(
                                        h["change_pct_str"],
                                        color=rx.cond(h["change_positive"], "green", "red"),
                                        weight="medium",
                                    )
                                ),
                                rx.table.cell(
                                    rx.cond(
                                        h["has_streak"],
                                        rx.badge(
                                            h["consecutive_days"].to_string() + "일",
                                            color_scheme=rx.cond(
                                                h["streak_hot"], "tomato", "amber"
                                            ),
                                            variant="solid", size="1",
                                        ),
                                        rx.text("-", color="gray", size="1"),
                                    )
                                ),
                                rx.table.cell(
                                    rx.cond(h["has_vol_rank"],  h["vol_rank_str"],  "-")
                                ),
                                rx.table.cell(
                                    rx.cond(h["has_rise_rank"], h["rise_rank_str"], "-")
                                ),
                                rx.table.cell(h["score_a_str"]),
                                rx.table.cell(
                                    rx.cond(h["has_score_b"], h["score_b_str"], "-")
                                ),
                                rx.table.cell(
                                    rx.button(
                                        "조회",
                                        size="1",
                                        variant="soft",
                                        color_scheme="blue",
                                        on_click=State.goto_lookup_from_leaders(h["code"], h["is_us"]),
                                    )
                                ),
                            ),
                        )
                    ),
                    variant="surface",
                    width="100%",
                ),
                    display=rx.breakpoints(initial="none", sm="none", md="block"),
                    width="100%",
                ),
                width="100%", spacing="0",
            ),
        ),
        width="100%",
        spacing="4",
    )


def _lookup_info_card(label: str, value) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.text(label, size="1", color="gray", weight="medium"),
            rx.text(value, size="3", weight="bold"),
            spacing="1",
            align="center",
        ),
        variant="surface",
        style={"text_align": "center", "min_width": "110px"},
    )


def lookup_tab() -> rx.Component:
    """종목 조회 탭 — 종목명/심볼 직접 입력으로 기본 정보 조회."""
    return rx.vstack(
        rx.heading("종목 조회", size="4"),
        # 검색 바
        rx.hstack(
            rx.input(
                placeholder="종목명 또는 심볼 (예: 삼성전자 / 005930 / AAPL)",
                value=State.lookup_query,
                on_change=State.set_lookup_query,
                on_key_down=State.handle_lookup_key,
                width="420px",
            ),
            rx.select(
                ["KR", "US"],
                value=State.lookup_market,
                on_change=State.set_lookup_market,
                width="90px",
            ),
            rx.button(
                "조회",
                on_click=State.do_lookup_stock,
                loading=State.lookup_loading,
                disabled=State.lookup_loading,
            ),
            align_items="center",
            spacing="3",
        ),
        # 에러 메시지
        rx.cond(
            State.lookup_error != "",
            rx.callout.root(
                rx.callout.text(State.lookup_error),
                color_scheme="red",
                variant="soft",
            ),
        ),
        # 로딩 중
        rx.cond(
            State.lookup_loading,
            rx.hstack(
                rx.spinner(size="3"),
                rx.text("데이터 조회 중...", color="gray"),
                spacing="2",
                align="center",
            ),
        ),
        # 결과 영역
        rx.cond(
            State.lookup_has_result,
            rx.vstack(
                # 종목 헤더
                rx.hstack(
                    rx.vstack(
                        rx.heading(State.lookup_name, size="5"),
                        rx.text(State.lookup_symbol, size="2", color="gray"),
                        spacing="0",
                        align="start",
                    ),
                    rx.spacer(),
                    rx.vstack(
                        rx.text(
                            State.lookup_price,
                            size="6",
                            weight="bold",
                        ),
                        rx.text(
                            State.lookup_change_pct,
                            size="3",
                            color=rx.cond(State.lookup_change_positive, "green", "red"),
                            weight="medium",
                        ),
                        spacing="0",
                        align="end",
                    ),
                    width="100%",
                    align="center",
                    padding="16px",
                    style={"border": "1px solid var(--gray-a6)", "border_radius": "8px"},
                ),
                # 정보 카드 그리드
                rx.grid(
                    _lookup_info_card("시가총액", State.lookup_market_cap),
                    _lookup_info_card("배당수익률", State.lookup_div_yield),
                    _lookup_info_card("PBR", State.lookup_pbr),
                    _lookup_info_card("PER", State.lookup_per),
                    _lookup_info_card("ROE", State.lookup_roe),
                    _lookup_info_card("PSR", State.lookup_psr),
                    _lookup_info_card("VWAP20", State.lookup_vwap),
                    _lookup_info_card("MFI", State.lookup_mfi),
                    columns="4",
                    spacing="3",
                    width="100%",
                ),
                # ── 매수 의견 점수 ───────────────────────────────────
                rx.cond(
                    State.lookup_buy_opinion != "",
                    rx.box(
                        rx.vstack(
                            # 헤더: 점수 + 의견 뱃지
                            rx.hstack(
                                rx.text("매수 의견 점수", weight="bold", size="2"),
                                rx.spacer(),
                                rx.badge(
                                    State.lookup_buy_score_str + "점",
                                    color_scheme="blue",
                                    variant="solid",
                                    size="2",
                                ),
                                rx.badge(
                                    State.lookup_buy_opinion,
                                    color_scheme=State.lookup_buy_opinion_color,
                                    variant="solid",
                                    size="2",
                                ),
                                width="100%",
                                align="center",
                                spacing="2",
                            ),
                            # 점수 항목 테이블
                            rx.table.root(
                                rx.table.header(
                                    rx.table.row(
                                        rx.table.column_header_cell("항목"),
                                        rx.table.column_header_cell("내용"),
                                        rx.table.column_header_cell("점수", justify="end"),
                                    )
                                ),
                                rx.table.body(
                                    rx.foreach(
                                        State.lookup_buy_score_items,
                                        lambda item: rx.table.row(
                                            rx.table.cell(
                                                rx.text(
                                                    item["label"],
                                                    weight="medium",
                                                    color=rx.cond(item["positive"], "green", "gray"),
                                                    size="2",
                                                )
                                            ),
                                            rx.table.cell(
                                                rx.text(item["detail"], size="2", color="gray")
                                            ),
                                            rx.table.cell(
                                                rx.badge(
                                                    item["score_str"],
                                                    color_scheme=rx.cond(item["positive"], "green", "gray"),
                                                    variant="soft",
                                                ),
                                                justify="end",
                                            ),
                                        ),
                                    )
                                ),
                                variant="surface",
                                width="100%",
                                size="1",
                            ),
                            # 점수 기준 안내
                            rx.hstack(
                                rx.badge("7~8 강력매수", color_scheme="green", variant="soft", size="1"),
                                rx.badge("5~6 매수검토", color_scheme="blue", variant="soft", size="1"),
                                rx.badge("3~4 중립", color_scheme="gray", variant="soft", size="1"),
                                rx.badge("0~2 관망", color_scheme="orange", variant="soft", size="1"),
                                rx.badge("음수 주의", color_scheme="red", variant="soft", size="1"),
                                spacing="2",
                                flex_wrap="wrap",
                            ),
                            spacing="3",
                            width="100%",
                        ),
                        padding="16px",
                        style={"border": "1px solid var(--gray-a6)", "border_radius": "8px"},
                        width="100%",
                    ),
                ),
                # ETF 구성종목 (ETF일 때만 표시)
                rx.cond(
                    State.lookup_is_etf,
                    rx.vstack(
                        rx.hstack(
                            rx.badge("ETF", color_scheme="violet", variant="solid", size="2"),
                            rx.text(State.lookup_etf_base_index, size="2", color="gray"),
                            spacing="2", align="center",
                        ),
                        rx.grid(
                            _lookup_info_card("NAV", State.lookup_etf_nav),
                            _lookup_info_card("운용보수", State.lookup_etf_fee),
                            _lookup_info_card("운용사", State.lookup_etf_issuer),
                            columns="3", spacing="3", width="100%",
                        ),
                        rx.text("구성종목 TOP 10", weight="bold", size="3"),
                        rx.table.root(
                            rx.table.header(
                                rx.table.row(
                                    rx.table.column_header_cell("순위"),
                                    rx.table.column_header_cell("코드"),
                                    rx.table.column_header_cell("종목명"),
                                    rx.table.column_header_cell("보유수량"),
                                    rx.table.column_header_cell("비중"),
                                )
                            ),
                            rx.table.body(
                                rx.foreach(
                                    State.lookup_etf_components,
                                    lambda r: rx.table.row(
                                        rx.table.cell(r["rank"]),
                                        rx.table.cell(r["code"]),
                                        rx.table.cell(r["name"]),
                                        rx.table.cell(r["count"]),
                                        rx.table.cell(
                                            rx.badge(r["weight"], color_scheme="violet", variant="soft")
                                        ),
                                    )
                                )
                            ),
                            variant="surface",
                            width="100%",
                            size="1",
                        ),
                        spacing="3",
                        width="100%",
                        padding="16px",
                        style={"border": "1px solid var(--violet-a6)", "border_radius": "8px"},
                    ),
                ),
                # 주가 차트
                rx.cond(
                    State.lookup_chart_data.length() > 0,
                    rx.box(
                        rx.vstack(
                            rx.hstack(
                                rx.text("주가 차트", weight="bold", size="2"),
                                rx.badge("종가", color_scheme="blue"),
                                rx.badge("VWAP20", color_scheme="amber"),
                                rx.badge("VWAP60", color_scheme="orange"),
                                rx.badge("TWAP20", color_scheme="green"),
                                rx.badge("TWAP60", color_scheme="red"),
                                spacing="2",
                                align_items="center",
                            ),
                            rx.recharts.composed_chart(
                                rx.recharts.line(
                                    data_key="종가",
                                    stroke="#2563eb",
                                    dot=False,
                                    type_="monotone",
                                    stroke_width=2,
                                    name="종가",
                                ),
                                rx.recharts.line(
                                    data_key="VWAP20",
                                    stroke="#f59e0b",
                                    dot=False,
                                    type_="monotone",
                                    stroke_dasharray="6 3",
                                    stroke_width=2,
                                    name="VWAP20",
                                ),
                                rx.recharts.line(
                                    data_key="VWAP60",
                                    stroke="#ea580c",
                                    dot=False,
                                    type_="monotone",
                                    stroke_dasharray="6 3",
                                    stroke_width=2,
                                    name="VWAP60",
                                ),
                                rx.recharts.line(
                                    data_key="MA20",
                                    stroke="#16a34a",
                                    dot=False,
                                    type_="monotone",
                                    stroke_width=1,
                                    name="TWAP20",
                                ),
                                rx.recharts.line(
                                    data_key="MA60",
                                    stroke="#dc2626",
                                    dot=False,
                                    type_="monotone",
                                    stroke_width=1,
                                    name="TWAP60",
                                ),
                                rx.recharts.x_axis(data_key="date", tick={"fontSize": 9}),
                                rx.recharts.y_axis(tick={"fontSize": 9}),
                                rx.recharts.cartesian_grid(stroke_dasharray="3 3"),
                                rx.recharts.tooltip(),
                                rx.recharts.legend(),
                                data=State.lookup_chart_data,
                                width="100%",
                                height=300,
                            ),
                            width="100%",
                            spacing="3",
                        ),
                        padding="16px",
                        border_radius="8px",
                        background="var(--gray-2)",
                        border="1px solid var(--gray-5)",
                        width="100%",
                    ),
                ),
                width="100%",
                spacing="4",
            ),
        ),
        width="100%",
        spacing="4",
    )


def holding_analysis_tab() -> rx.Component:
    """보유종목 포트폴리오 분석 탭."""
    return rx.vstack(
        rx.heading("포트폴리오", size="4"),
        rx.cond(
            State.portfolio_count == 0,
            rx.callout.root(
                rx.callout.text("등록된 보유 종목이 없습니다. 분석 탭에서 '+ 보유 추가' 버튼을 누르세요."),
                color_scheme="gray",
                variant="soft",
            ),
            rx.vstack(
                # 집계 요약 카드
                rx.grid(
                    rx.box(
                        rx.vstack(
                            rx.text("총 종목 수", size="1", color="gray"),
                            rx.hstack(
                                rx.text(State.portfolio_count, size="6", weight="bold"),
                                rx.text("개", size="3", color="gray"),
                                spacing="1",
                                align_items="baseline",
                            ),
                            spacing="1",
                            align_items="start",
                        ),
                        padding="16px",
                        border_radius="8px",
                        background="var(--blue-2)",
                        border="1px solid var(--blue-4)",
                    ),
                    rx.box(
                        rx.vstack(
                            rx.text("총 투자금", size="1", color="gray"),
                            rx.hstack(
                                rx.text(State.portfolio_total_investment, size="6", weight="bold"),
                                rx.text("원", size="3", color="gray"),
                                spacing="1",
                                align_items="baseline",
                            ),
                            spacing="1",
                            align_items="start",
                        ),
                        padding="16px",
                        border_radius="8px",
                        background="var(--gray-2)",
                        border="1px solid var(--gray-4)",
                    ),
                    rx.box(
                        rx.vstack(
                            rx.text("예상 손익", size="1", color="gray"),
                            rx.hstack(
                                rx.text(
                                    State.portfolio_total_pnl,
                                    size="6",
                                    weight="bold",
                                    color=rx.cond(State.portfolio_total_pnl >= 0, "green", "red"),
                                ),
                                rx.text("원", size="3", color="gray"),
                                spacing="1",
                                align_items="baseline",
                            ),
                            spacing="1",
                            align_items="start",
                        ),
                        padding="16px",
                        border_radius="8px",
                        background=rx.cond(
                            State.portfolio_total_pnl >= 0, "var(--green-2)", "var(--red-2)"
                        ),
                        border=rx.cond(
                            State.portfolio_total_pnl >= 0,
                            "1px solid var(--green-4)",
                            "1px solid var(--red-4)",
                        ),
                    ),
                    rx.box(
                        rx.vstack(
                            rx.text("손익률", size="1", color="gray"),
                            rx.hstack(
                                rx.text(
                                    State.portfolio_pnl_pct,
                                    size="6",
                                    weight="bold",
                                    color=rx.cond(State.portfolio_pnl_pct >= 0, "green", "red"),
                                ),
                                rx.text("%", size="3", color="gray"),
                                spacing="1",
                                align_items="baseline",
                            ),
                            spacing="1",
                            align_items="start",
                        ),
                        padding="16px",
                        border_radius="8px",
                        background=rx.cond(
                            State.portfolio_pnl_pct >= 0, "var(--green-2)", "var(--red-2)"
                        ),
                        border=rx.cond(
                            State.portfolio_pnl_pct >= 0,
                            "1px solid var(--green-4)",
                            "1px solid var(--red-4)",
                        ),
                    ),
                    columns=rx.breakpoints(initial="2", sm="2", md="4"),
                    spacing="4",
                    width="100%",
                ),
                # ── 알림 배너 ────────────────────────────────────────
                rx.cond(
                    State.portfolio_alert_count > 0,
                    rx.callout.root(
                        rx.callout.text(
                            rx.hstack(
                                rx.icon("triangle-alert", size=14),
                                rx.text(
                                    State.portfolio_alert_count.to_string()
                                    + "개 종목에 알림이 있습니다 — 손절(-8%) 또는 목표가(+20%) 도달",
                                    size="2",
                                ),
                                spacing="2", align="center",
                            )
                        ),
                        color_scheme="amber", variant="soft",
                    ),
                ),
                # 종목별 손익
                rx.text("종목별 손익 현황", weight="bold", size="3"),
                # ── 모바일 카드 뷰 ─────────────────────────────────
                rx.box(
                    rx.foreach(
                        State.holdings_analysis,
                        lambda h: rx.card(
                            rx.vstack(
                                rx.hstack(
                                    rx.text(h["name"], weight="bold", size="3"),
                                    rx.badge(h["market"],
                                        color_scheme=rx.cond(h["is_us"], "blue", "green"),
                                        variant="soft"),
                                    rx.cond(h["alert_stop_loss"],
                                        rx.badge("손절", color_scheme="red", variant="solid", size="1"),
                                        rx.cond(h["alert_target"],
                                            rx.badge("목표", color_scheme="green", variant="solid", size="1"),
                                            rx.fragment(),
                                        ),
                                    ),
                                    rx.spacer(),
                                    rx.cond(
                                        h["has_buy"],
                                        rx.badge(
                                            rx.text(h["pnl_pct"], "%"),
                                            color_scheme=rx.cond(h["pct_positive"], "green", "red"),
                                        ),
                                        rx.fragment(),
                                    ),
                                    width="100%", align="center",
                                ),
                                rx.hstack(
                                    rx.vstack(
                                        rx.text("매수가", size="1", color="gray"),
                                        rx.text(rx.cond(h["has_buy"], h["buy_price"], "-"), size="2"),
                                        spacing="0",
                                    ),
                                    rx.vstack(
                                        rx.text("현재가", size="1", color="gray"),
                                        rx.text(h["close"], size="2", weight="medium"),
                                        spacing="0",
                                    ),
                                    rx.vstack(
                                        rx.text("손익", size="1", color="gray"),
                                        rx.cond(
                                            h["has_buy"],
                                            rx.text(h["pnl"],
                                                color=rx.cond(h["pnl_positive"], "green", "red"),
                                                size="2", weight="bold"),
                                            rx.text("-", size="2", color="gray"),
                                        ),
                                        spacing="0",
                                    ),
                                    rx.vstack(
                                        rx.text("MFI", size="1", color="gray"),
                                        rx.text(h["mfi"], size="2"),
                                        spacing="0",
                                    ),
                                    justify="between", width="100%",
                                ),
                                rx.hstack(
                                    rx.button("분석", size="1", variant="soft", color_scheme="blue",
                                        on_click=State.select_holding_for_analysis(h["holding_id"])),
                                    rx.button("삭제", size="1", variant="soft", color_scheme="red",
                                        on_click=State.remove_holding(h["holding_id"])),
                                    spacing="2",
                                ),
                                spacing="2", width="100%",
                            ),
                            width="100%",
                        ),
                    ),
                    display=rx.breakpoints(initial="block", sm="block", md="none"),
                    width="100%",
                ),
                # ── 데스크탑 테이블 ─────────────────────────────────
                rx.box(
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                rx.table.column_header_cell("종목명"),
                                rx.table.column_header_cell("시장"),
                                rx.table.column_header_cell("매수가"),
                                rx.table.column_header_cell("현재가"),
                                rx.table.column_header_cell("수량"),
                                rx.table.column_header_cell("투자금"),
                                rx.table.column_header_cell("손익금액"),
                                rx.table.column_header_cell("손익률(%)"),
                                rx.table.column_header_cell("알림"),
                                rx.table.column_header_cell("MFI"),
                                rx.table.column_header_cell("VWAP괴리(%)"),
                                rx.table.column_header_cell("메모"),
                                rx.table.column_header_cell(""),
                            )
                        ),
                        rx.table.body(
                            rx.foreach(
                                State.holdings_analysis,
                                lambda h: rx.table.row(
                                    rx.table.cell(h["name"]),
                                    rx.table.cell(
                                        rx.badge(h["market"],
                                            color_scheme=rx.cond(h["is_us"], "blue", "green"),
                                            variant="soft")
                                    ),
                                    rx.table.cell(
                                        rx.cond(h["has_buy"], h["buy_price"], rx.text("-", color="gray"))
                                    ),
                                    rx.table.cell(h["close"]),
                                    rx.table.cell(
                                        rx.cond(h["has_quantity"], h["quantity"], rx.text("-", color="gray"))
                                    ),
                                    rx.table.cell(
                                        rx.cond(h["has_investment"], h["investment"], rx.text("-", color="gray"))
                                    ),
                                    rx.table.cell(
                                        rx.cond(
                                            h["has_buy"],
                                            rx.text(h["pnl"],
                                                color=rx.cond(h["pnl_positive"], "green", "red"),
                                                weight="bold"),
                                            rx.text("-", color="gray"),
                                        )
                                    ),
                                    rx.table.cell(
                                        rx.cond(
                                            h["has_buy"],
                                            rx.badge(rx.text(h["pnl_pct"], "%"),
                                                color_scheme=rx.cond(h["pct_positive"], "green", "red")),
                                            rx.text("-", color="gray"),
                                        )
                                    ),
                                    rx.table.cell(
                                        rx.cond(h["alert_stop_loss"],
                                            rx.badge("손절", color_scheme="red", variant="solid", size="1"),
                                            rx.cond(h["alert_target"],
                                                rx.badge("목표", color_scheme="green", variant="solid", size="1"),
                                                rx.text("-", color="gray", size="1"),
                                            ),
                                        )
                                    ),
                                    rx.table.cell(h["mfi"]),
                                    rx.table.cell(h["vwap_gap"]),
                                    rx.table.cell(
                                        rx.cond(h["has_memo"], h["memo"], rx.text("-", color="gray"))
                                    ),
                                    rx.table.cell(
                                        rx.hstack(
                                            rx.button("분석", size="1", variant="soft", color_scheme="blue",
                                                on_click=State.select_holding_for_analysis(h["holding_id"])),
                                            rx.button("삭제", size="1", variant="soft", color_scheme="red",
                                                on_click=State.remove_holding(h["holding_id"])),
                                            spacing="2",
                                        )
                                    ),
                                ),
                            )
                        ),
                        variant="surface",
                        width="100%",
                    ),
                    display=rx.breakpoints(initial="none", sm="none", md="block"),
                    width="100%",
                ),
                width="100%",
                spacing="4",
            ),
        ),
        width="100%",
        spacing="4",
    )


def app_header() -> rx.Component:
    return rx.hstack(
        rx.text("⚡ QuantMaster Pro", size="4", weight="bold", color="blue"),
        rx.text("v2.0", size="1", color="gray", margin_top="4px"),
        spacing="2",
        align="end",
        padding_bottom="8px",
    )


def tracker_tab() -> rx.Component:
    """성과 추적 탭 — 발굴 종목 수익률 추적."""

    def _mode_btn(val: str, label: str) -> rx.Component:
        return rx.button(
            label, size="1",
            variant=rx.cond(State.tracker_filter_mode == val, "solid", "soft"),
            color_scheme="blue",
            on_click=State.set_tracker_filter_mode(val),
        )

    def _mkt_btn(val: str, label: str) -> rx.Component:
        return rx.button(
            label, size="1",
            variant=rx.cond(State.tracker_filter_market == val, "solid", "soft"),
            color_scheme="green",
            on_click=State.set_tracker_filter_market(val),
        )

    def _pick_row(p: dict) -> rx.Component:
        return rx.table.row(
            rx.table.cell(rx.text(p["scan_date"], size="1", color="gray")),
            rx.table.cell(rx.text(p["scan_mode_label"], size="1")),
            rx.table.cell(rx.text(p["market"], size="1")),
            rx.table.cell(rx.text(p["name"], weight="medium", size="2")),
            rx.table.cell(rx.text(p["close_at_str"], size="1")),
            rx.table.cell(rx.text(p["cur_close_str"], size="1")),
            rx.table.cell(
                rx.cond(
                    p["ret_known"],
                    rx.text(
                        p["ret_str"],
                        color=rx.cond(p["ret_positive"], "green", "red"),
                        weight="bold", size="2",
                    ),
                    rx.text("추적중", color="gray", size="1"),
                )
            ),
            rx.table.cell(rx.text(p["days_elapsed"], "일", size="1", color="gray")),
        )

    summary = State.tracker_summary

    return rx.vstack(
        # 헤더
        rx.hstack(
            rx.heading("성과 추적", size="4"),
            rx.spacer(),
            rx.button(
                "스캔 실행",
                on_click=State.run_auto_scan_now,
                loading=State.tracker_updating,
                color_scheme="blue", size="2",
            ),
            rx.button(
                "가격 업데이트",
                on_click=State.update_tracker_prices,
                loading=State.tracker_updating,
                color_scheme="green", size="2",
            ),
            rx.button(
                "새로고침",
                on_click=State.load_tracker_picks,
                variant="soft", size="2",
            ),
            width="100%", align="center",
        ),
        # 상태 메시지
        rx.cond(
            State.tracker_status != "",
            rx.callout(
                State.tracker_status,
                color=rx.cond(State.tracker_status.contains("오류"), "red", "green"),
                size="1", width="100%",
            ),
        ),
        # 요약 카드
        rx.cond(
            State.tracker_picks.length() > 0,
            rx.hstack(
                rx.box(
                    rx.text("추적 종목", size="1", color="gray"),
                    rx.text(summary["total"], weight="bold", size="5"),
                    background="white", border_radius="8px",
                    padding="12px 16px", box_shadow="0 1px 4px rgba(0,0,0,.08)",
                ),
                rx.box(
                    rx.text("승률", size="1", color="gray"),
                    rx.text(summary["win_rate_str"], weight="bold", size="5",
                            color=rx.cond(summary["avg_positive"], "green", "red")),
                    background="white", border_radius="8px",
                    padding="12px 16px", box_shadow="0 1px 4px rgba(0,0,0,.08)",
                ),
                rx.box(
                    rx.text("평균 수익률", size="1", color="gray"),
                    rx.text(summary["avg_ret_str"], weight="bold", size="5",
                            color=rx.cond(summary["avg_positive"], "green", "red")),
                    background="white", border_radius="8px",
                    padding="12px 16px", box_shadow="0 1px 4px rgba(0,0,0,.08)",
                ),
                rx.box(
                    rx.text("최고 수익", size="1", color="gray"),
                    rx.text(summary["best_str"], weight="bold", size="2", color="green"),
                    background="white", border_radius="8px",
                    padding="12px 16px", box_shadow="0 1px 4px rgba(0,0,0,.08)",
                    flex="1",
                ),
                spacing="3", width="100%",
            ),
        ),
        # 필터
        rx.hstack(
            rx.text("모드:", size="1", color="gray"),
            _mode_btn("all",      "전체"),
            _mode_btn("quant",    "퀀트"),
            _mode_btn("pullback", "눌림목"),
            _mode_btn("whale",    "세력"),
            rx.separator(orientation="vertical"),
            rx.text("시장:", size="1", color="gray"),
            _mkt_btn("all",    "전체"),
            _mkt_btn("KOSPI",  "KOSPI"),
            _mkt_btn("KOSDAQ", "KOSDAQ"),
            _mkt_btn("SP500",  "SP500"),
            flex_wrap="wrap",
            spacing="2",
        ),
        rx.text("최근 30거래일 발굴 종목 · 매일 16:20 자동 가격 업데이트",
                size="1", color="gray"),
        # 테이블
        rx.cond(
            State.tracker_picks.length() == 0,
            rx.center(
                rx.text(
                    "'스캔 실행' 버튼으로 첫 발굴을 시작하거나 "
                    "scripts/run_auto_scan.py 를 실행하세요.",
                    color="gray", size="2",
                ),
                padding_y="40px",
            ),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("발굴일"),
                        rx.table.column_header_cell("모드"),
                        rx.table.column_header_cell("시장"),
                        rx.table.column_header_cell("종목명"),
                        rx.table.column_header_cell("발굴가"),
                        rx.table.column_header_cell("현재가"),
                        rx.table.column_header_cell("수익률"),
                        rx.table.column_header_cell("경과"),
                    )
                ),
                rx.table.body(rx.foreach(State.tracker_picks, _pick_row)),
                width="100%", size="2",
            ),
        ),
        width="100%", spacing="3", padding_bottom="8px",
    )


def report_tab() -> rx.Component:
    """리포트 탭 — 일별/주간 HTML 리포트 생성 및 목록."""

    def _file_row(r: dict) -> rx.Component:
        return rx.table.row(
            rx.table.cell(rx.text(r["date_str"], weight="medium")),
            rx.table.cell(rx.text(r["size_kb"], " KB", color="gray", size="1")),
            rx.table.cell(
                rx.button(
                    "📂 열기",
                    on_click=State.open_report_file(r["filepath"]),
                    variant="ghost",
                    size="1",
                    color_scheme="blue",
                    cursor="pointer",
                )
            ),
        )

    return rx.vstack(
        # 헤더
        rx.hstack(
            rx.heading("리포트", size="4"),
            rx.spacer(),
            rx.button(
                "일별 리포트 생성",
                on_click=State.generate_daily_report_event,
                loading=State.report_generating,
                color_scheme="blue",
                size="2",
            ),
            rx.button(
                "주간 리포트 생성",
                on_click=State.generate_weekly_report_event,
                loading=State.report_generating,
                color_scheme="green",
                size="2",
            ),
            rx.button(
                "목록 새로고침",
                on_click=State.load_report_files,
                variant="soft",
                size="2",
            ),
            width="100%",
            align="center",
        ),
        # 상태 메시지
        rx.cond(
            State.report_status != "",
            rx.callout(
                State.report_status,
                color=rx.cond(
                    State.report_status.contains("오류"),
                    "red",
                    "green",
                ),
                size="1",
                width="100%",
            ),
        ),
        # 안내
        rx.text(
            "생성된 리포트는 quantReports/ 폴더에 저장됩니다. "
            "'📂 열기' 버튼을 클릭하면 기본 브라우저로 파일이 열립니다.",
            size="1",
            color="gray",
        ),
        # 파일 목록 테이블
        rx.cond(
            State.report_files.length() == 0,
            rx.center(
                rx.text("리포트 없음 — '일별 리포트 생성' 버튼을 눌러 첫 리포트를 만드세요.",
                        color="gray", size="2"),
                padding_y="40px",
            ),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("날짜"),
                        rx.table.column_header_cell("크기"),
                        rx.table.column_header_cell("열기"),
                    )
                ),
                rx.table.body(
                    rx.foreach(State.report_files, _file_row),
                ),
                width="100%",
                size="2",
            ),
        ),
        width="100%",
        spacing="3",
        padding_bottom="8px",
    )


def monitor_tab() -> rx.Component:
    """작업현황 탭 — 실행 중인 백그라운드 작업 목록 + 중단 버튼."""

    def _stop_badge(label: str) -> rx.Component:
        return rx.badge(label, color_scheme="orange", size="1")

    def _task_card(title, detail, stop_btn=None) -> rx.Component:
        return rx.card(
            rx.hstack(
                rx.spinner(size="3"),
                rx.vstack(
                    rx.hstack(
                        rx.badge("실행 중", color_scheme="blue", size="1"),
                        rx.text(title, size="3", weight="bold"),
                        spacing="2",
                        align="center",
                    ),
                    rx.text(detail, size="2", color="gray"),
                    spacing="1",
                    align="start",
                    flex="1",
                ),
                rx.spacer(),
                stop_btn if stop_btn is not None else rx.box(),
                align="center",
                width="100%",
                spacing="3",
            ),
            width="100%",
            variant="surface",
        )

    scan_name = rx.cond(State.scan_mode == "whale", "세력 탐지",
                rx.cond(State.scan_mode == "pullback", "눌림목 스캔",
                rx.cond(State.scan_mode == "trend", "추세추종 스캔",
                rx.cond(State.scan_mode == "defensive", "하락방어 스캔",
                rx.cond(State.scan_mode == "stock_momentum", "기간모멘텀 스캔",
                "퀀트 스캔")))))

    scan_progress = rx.cond(
        State.scan_mode == "whale",
        rx.cond(State.whale_progress != "", State.whale_progress, State.status_msg),
        rx.cond(State.trend_progress != "", State.trend_progress, State.status_msg),
    )

    scan_stop_btn = rx.cond(
        State.scan_mode == "whale",
        rx.button(
            rx.cond(State.whale_stop_requested, "중단 중...", "중단"),
            on_click=State.stop_whale_scan,
            disabled=State.whale_stop_requested,
            color_scheme="red",
            size="1",
        ),
        rx.button(
            rx.cond(State.scan_stop_requested, "중단 중...", "중단"),
            on_click=State.stop_general_scan,
            disabled=State.scan_stop_requested,
            color_scheme="red",
            size="1",
        ),
    )

    return rx.vstack(
        rx.hstack(
            rx.heading("작업 현황", size="5"),
            rx.text("· 실행 중인 백그라운드 작업을 확인하고 중단할 수 있습니다.",
                    size="2", color="gray"),
            spacing="3",
            align="center",
        ),
        rx.divider(),
        rx.cond(
            State.has_active_tasks,
            rx.vstack(
                rx.cond(
                    State.is_scanning,
                    _task_card(scan_name, scan_progress, scan_stop_btn),
                ),
                rx.cond(
                    State.is_backtesting,
                    _task_card("백테스트", State.status_msg),
                ),
                rx.cond(
                    State.leaders_loading,
                    _task_card(
                        "주도주 데이터 로드",
                        rx.cond(State.leaders_scan_progress != "",
                                State.leaders_scan_progress, "데이터 불러오는 중..."),
                    ),
                ),
                rx.cond(
                    State.report_generating,
                    _task_card("리포트 생성", State.report_status),
                ),
                rx.cond(
                    State.leaders_prefetch_status != "",
                    _task_card("캐시 업데이트 (백그라운드)", State.leaders_prefetch_status),
                ),
                width="100%",
                spacing="3",
            ),
            rx.center(
                rx.vstack(
                    rx.icon("circle-check", size=48, color="green"),
                    rx.text("현재 실행 중인 작업이 없습니다.",
                            size="3", color="gray", weight="medium"),
                    rx.text("스캔·백테스트·리포트 생성이 시작되면 여기에 표시됩니다.",
                            size="2", color="gray"),
                    spacing="2",
                    align="center",
                ),
                padding_y="64px",
                width="100%",
            ),
        ),
        width="100%",
        spacing="4",
        padding_bottom="16px",
    )


def main_content() -> rx.Component:
    return rx.vstack(
        app_header(),
        rx.tabs.root(
        rx.tabs.list(
            rx.tabs.trigger("시장모멘텀", value="momentum",
                on_click=State.set_tab("momentum")),
            rx.tabs.trigger("섹터모멘텀", value="sector",
                on_click=State.set_tab("sector")),
            rx.tabs.trigger("기간모멘텀", value="pmom",
                on_click=State.set_tab("pmom")),
            rx.tabs.trigger("당일주도주", value="leaders",
                on_click=State.set_tab("leaders")),
            rx.tabs.trigger("스캐너", value="scanner",
                on_click=State.set_tab("scanner")),
            rx.tabs.trigger("분석", value="analysis",
                on_click=State.set_tab("analysis")),
            rx.tabs.trigger("종목조회", value="lookup",
                on_click=State.set_tab("lookup")),
            rx.tabs.trigger("포트폴리오", value="portfolio",
                on_click=State.set_tab("portfolio")),
            rx.tabs.trigger("히스토리", value="history",
                on_click=State.set_tab("history")),
            rx.tabs.trigger("리포트", value="report",
                on_click=State.set_tab("report")),
            rx.tabs.trigger("성과추적", value="tracker",
                on_click=State.set_tab("tracker")),
            rx.tabs.trigger("작업현황", value="monitor",
                on_click=State.set_tab("monitor")),
            overflow_x="auto",
            white_space="nowrap",
            width="100%",
        ),
        rx.tabs.content(
            rx.box(scanner_tab(), padding_top="16px"),
            value="scanner",
        ),
        rx.tabs.content(
            rx.box(analysis_tab(), padding_top="16px"),
            value="analysis",
        ),
        rx.tabs.content(
            rx.box(history_tab(), padding_top="16px"),
            value="history",
        ),
        rx.tabs.content(
            rx.box(holding_analysis_tab(), padding_top="16px"),
            value="portfolio",
        ),
        rx.tabs.content(
            rx.box(pmom_tab(), padding_top="16px"),
            value="pmom",
        ),
        rx.tabs.content(
            rx.box(leaders_tab(), padding_top="16px"),
            value="leaders",
        ),
        rx.tabs.content(
            rx.box(lookup_tab(), padding_top="16px"),
            value="lookup",
        ),
        rx.tabs.content(
            rx.box(momentum_tab(), padding_top="16px"),
            value="momentum",
        ),
        rx.tabs.content(
            rx.box(sector_tab(), padding_top="16px"),
            value="sector",
        ),
        rx.tabs.content(
            rx.box(report_tab(), padding_top="16px"),
            value="report",
        ),
        rx.tabs.content(
            rx.box(tracker_tab(), padding_top="16px"),
            value="tracker",
        ),
        rx.tabs.content(
            rx.box(monitor_tab(), padding_top="16px"),
            value="monitor",
        ),
        value=State.active_tab,
        width="100%",
        ),
        spacing="0",
        width="100%",
    )


def index() -> rx.Component:
    return rx.box(
        rx.box(
            main_content(),
            padding=rx.breakpoints(initial="12px", sm="16px", md="24px"),
        ),
        min_height="100vh",
        width="100%",
        overflow_y="auto",
    )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = rx.App(
    theme=rx.theme(
        appearance="light",
        accent_color="blue",
        gray_color="slate",
        radius="medium",
    )
)
app.add_page(
    index,
    title="QuantMaster Pro",
    on_load=[State.load_holdings_from_db, State.load_leaders_from_cache_on_init, State.do_prefetch_momentum_bg],
)
