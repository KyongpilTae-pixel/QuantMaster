"""
QuantMaster Pro v2.0 — Reflex UI
Hybrid Quant & Technical Breakout Scanner
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import math
from typing import List

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
    # UI
    sidebar_open: bool = False

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

    # 하락장 방어 스캔
    defensive_results: List[dict] = []
    defensive_period: int = 60           # 분석 기간 (일)
    defensive_max_beta: List[float] = [0.8]  # slider → List[float]
    defensive_min_mktcap: int = 10_000   # 최소 시가총액 (억원)

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

    # UI state
    is_scanning: bool = False
    is_backtesting: bool = False
    status_msg: str = ""
    active_tab: str = "scanner"

    # ------------------------------------------------------------------
    # Setters (explicit — required in Reflex 0.8+)
    # ------------------------------------------------------------------

    def set_market(self, value: str):
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

    def toggle_sidebar(self):
        self.sidebar_open = not self.sidebar_open

    def set_scan_mode(self, value: str):
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
            df = await asyncio.to_thread(loader.get_ohlcv, holding.symbol, 600)
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
            psr_data = await asyncio.to_thread(
                loader.get_quarterly_psr, holding.symbol, holding.market
            )
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
            })
        self.holdings_analysis = analysis
        self.portfolio_count = len(rows)
        self.portfolio_total_investment = round(total_investment, 0)
        self.portfolio_total_pnl = round(total_pnl, 0)
        self.portfolio_pnl_pct = (
            round(total_pnl / total_investment * 100, 1) if total_investment > 0 else 0.0
        )

    async def stop_whale_scan(self):
        """탐색 중단 요청 (다음 단계 시작 전 반영)."""
        self.whale_stop_requested = True
        self.whale_progress = "종목 분석을 마무리하는 중입니다. 잠시만 기다려 주세요..."
        self.status_msg = "탐색 중단 요청됨"
        yield

    def set_tab(self, tab: str):
        self.active_tab = tab
        if tab == "history":
            from utils.scan_db import load_run_list
            runs = load_run_list()
            self.saved_runs = [SavedRun(run_id=r["id"], label=r["label"]) for r in runs]
        elif tab == "portfolio":
            self.load_holdings_from_db()

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

    async def fetch_momentum(self):
        from utils.momentum_scanner import fetch_momentum_data
        self.momentum_loading = True
        self.momentum_error = ""
        self.momentum_rows = []
        self.momentum_recommendation = ""
        yield
        try:
            r = await asyncio.to_thread(fetch_momentum_data)
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
            r = await asyncio.to_thread(run_backtest, self.momentum_bt_years)
            self.momentum_bt_chart = r["chart_data"]
            self.momentum_bt_summary = r["summary"]
            self.momentum_bt_error = r.get("error", "")
        except Exception as e:
            self.momentum_bt_error = f"오류: {e}"
        finally:
            self.momentum_bt_loading = False
        yield

    def set_leaders_market(self, v: str):
        self.leaders_market = v

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
        if v == self.leaders_type_filter:
            return
        self.leaders_type_filter = v
        if self.leaders_data_raw:
            self._apply_filter_and_sort()

    async def do_fetch_leaders(self):
        if self.leaders_loading:
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
        yield

        import asyncio
        from utils.data_loader import fetch_leaders_combined

        try:
            data = await asyncio.to_thread(
                fetch_leaders_combined, self.leaders_market
            )
            # KR 시장은 캐시도 갱신
            if self.leaders_market in ("KOSPI", "KOSDAQ"):
                from utils.data_loader import save_leaders_cache
                await asyncio.to_thread(save_leaders_cache, self.leaders_market, data)
            self.leaders_data_raw = data
            self._apply_filter_and_sort()
        except Exception as e:
            self.leaders_error = str(e)
        finally:
            self.leaders_loading = False

    async def do_compute_score_b(self):
        if not self.leaders_data_raw:
            return
        # Reflex 리액티브 래퍼를 순수 Python 객체로 변환 후 스레드에 전달
        raw_snapshot = [dict(item) for item in self.leaders_data_raw]
        self.leaders_b_loading = True
        yield

        import asyncio
        from utils.data_loader import compute_score_b

        try:
            updated = await asyncio.to_thread(compute_score_b, raw_snapshot)
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

        result = await asyncio.to_thread(fetch_stock_info, code, self.lookup_market)
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

        result = await asyncio.to_thread(fetch_stock_info, q, self.lookup_market)

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
                df = await asyncio.to_thread(loader.get_ohlcv, w_target.symbol, 600)
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
                    idx_df = fdr.DataReader(
                        _INDEX_FDR.get(w_target.market, "KS11"),
                        start_dt.strftime("%Y-%m-%d"),
                        end_dt.strftime("%Y-%m-%d"),
                    )
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
            df = await asyncio.to_thread(loader.get_ohlcv, target.symbol, 600)
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
            psr_data = await asyncio.to_thread(
                loader.get_quarterly_psr, target.symbol, target.market_raw
            )
            self.psr_chart_data = psr_data

        except Exception:
            pass
        finally:
            self.is_loading_chart = False
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
                ctx = await asyncio.to_thread(
                    scanner.prepare,
                    self.market,
                    self.use_alpha,
                    self.use_short_filter,
                )
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

                    new = await asyncio.to_thread(
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
                    )
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

        # ── 하락방어 스캔 ────────────────────────────────────────────────
        if self.scan_mode == "defensive":
            from utils.defensive_scanner import scan_defensive_stocks
            self.is_scanning = True
            self.defensive_results = []
            mkt = self.market if self.market in ("KOSPI", "KOSDAQ") else "KOSPI"
            self.status_msg = f"{mkt} 하락방어 종목 분석 중... (약 1~2분 소요)"
            yield
            try:
                raw = await asyncio.to_thread(
                    scan_defensive_stocks,
                    mkt,
                    self.defensive_period,
                    self.defensive_max_beta[0],
                    self.defensive_min_mktcap,
                    30,
                )
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

        # ── 퀀트 스캔 ────────────────────────────────────────────────────
        self.is_scanning = True
        self.status_msg = "시장 데이터 수집 중..."
        self.scan_results = []
        yield

        try:
            scanner = QuantScanner()
            vwap = int(self.vwap_period)
            results = await asyncio.to_thread(
                scanner.run_advanced_scan,
                self.pbr_limit[0],
                vwap,
                10,
                self.market,
                self.min_cap_label,
            )

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
            result = await asyncio.to_thread(
                bt.run,
                target_symbol,
                target_name,
                int(self.vwap_period),
            )

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
    """사이드바 컨트롤 내용 — 데스크탑/모바일 드로어 공통."""
    return rx.vstack(
        rx.text("스캔 모드", size="2", color="gray"),
        rx.select.root(
            rx.select.trigger(placeholder="모드 선택"),
            rx.select.content(
                rx.select.item("퀀트 스캔", value="quant"),
                rx.select.item("세력 탐지", value="whale"),
                rx.select.item("하락방어", value="defensive"),
            ),
            value=State.scan_mode,
            on_change=State.set_scan_mode,
            width="100%",
        ),

        rx.text("시장", size="2", color="gray"),
        rx.select.root(
            rx.select.trigger(placeholder="시장 선택"),
            rx.select.content(
                rx.select.group(
                    rx.select.label("한국 주식"),
                    rx.select.item("KOSPI", value="KOSPI"),
                    rx.select.item("KOSDAQ", value="KOSDAQ"),
                ),
                rx.select.separator(),
                rx.select.group(
                    rx.select.label("한국 ETF"),
                    rx.select.item("KR-ETF (기술적 스캔)", value="KR-ETF"),
                ),
                rx.select.separator(),
                rx.select.group(
                    rx.select.label("미국"),
                    rx.select.item("S&P 500", value="SP500"),
                    rx.select.item("NASDAQ", value="NASDAQ"),
                ),
                rx.select.separator(),
                rx.select.group(
                    rx.select.label("미국 ETF"),
                    rx.select.item("US-ETF (기술적 스캔)", value="US-ETF"),
                ),
            ),
            value=State.market,
            on_change=State.set_market,
            width="100%",
        ),

        rx.cond(
            State.scan_mode == "quant",
            # ── 퀀트 전용 옵션 ───────────────────────────────────
            rx.vstack(
                rx.hstack(
                    rx.text("PBR 한도: ", size="2", color="gray"),
                    rx.text(State.pbr_limit[0], size="2"),
                ),
                rx.slider(
                    min=0.5,
                    max=2.0,
                    step=0.1,
                    value=State.pbr_limit,
                    on_change=State.set_pbr_limit,
                    width="100%",
                ),
                rx.text("최소 시가총액", size="2", color="gray"),
                rx.select.root(
                    rx.select.trigger(placeholder="시가총액 선택"),
                    rx.select.content(
                        rx.select.item("전체", value="전체"),
                        rx.select.item("소형주+ (KR:300억 / US:$2B)", value="소형주+"),
                        rx.select.item("중형주+ (KR:3000억 / US:$10B)", value="중형주+"),
                        rx.select.item("대형주+ (KR:1조 / US:$50B)", value="대형주+"),
                    ),
                    value=State.min_cap_label,
                    on_change=State.set_min_cap_label,
                    width="100%",
                ),
                rx.text("VWAP 기간", size="2", color="gray"),
                rx.select.root(
                    rx.select.trigger(placeholder="기간 선택"),
                    rx.select.content(
                        rx.select.item("20일", value="20"),
                        rx.select.item("60일", value="60"),
                        rx.select.item("120일", value="120"),
                    ),
                    value=State.vwap_period,
                    on_change=State.set_vwap_period,
                    width="100%",
                ),
                spacing="3",
                width="100%",
            ),
            rx.cond(
                State.scan_mode == "whale",
                # ── 세력 탐지 전용 옵션 ──────────────────────────────
                rx.vstack(
                    rx.text("세력 탐지 옵션", size="2", color="gray"),
                    rx.hstack(
                        rx.checkbox(
                            checked=State.use_alpha,
                            on_change=State.set_use_alpha,
                        ),
                        rx.text("지수 대비 알파 필터", size="2"),
                        spacing="2",
                        align_items="center",
                    ),
                    rx.hstack(
                        rx.checkbox(
                            checked=State.use_short_filter,
                            on_change=State.set_use_short_filter,
                        ),
                        rx.vstack(
                            rx.text("공매도 잔고 필터", size="2"),
                            rx.text("(미국 시장만 적용)", size="1", color="gray"),
                            spacing="0",
                            align_items="start",
                        ),
                        spacing="2",
                        align_items="center",
                    ),
                    rx.divider(),
                    rx.text("최대 탐색 시간", size="2", color="gray"),
                    rx.hstack(
                        rx.input(
                            value=State.whale_max_minutes,
                            on_change=State.set_whale_max_minutes,
                            type="number",
                            min="1",
                            max="30",
                            width="70px",
                        ),
                        rx.text("분 (1~30)", size="1", color="gray"),
                        spacing="2",
                        align_items="center",
                    ),
                    rx.cond(
                        State.whale_progress != "",
                        rx.box(
                            rx.text(
                                State.whale_progress,
                                size="1",
                                color="blue",
                                white_space="pre-wrap",
                            ),
                            padding="8px",
                            border_radius="6px",
                            background="var(--blue-2)",
                            border="1px solid var(--blue-4)",
                            width="100%",
                        ),
                    ),
                    spacing="3",
                    width="100%",
                ),
                # ── 하락방어 전용 옵션 ───────────────────────────────
                rx.vstack(
                    rx.text("분석 기간", size="2", color="gray"),
                    rx.hstack(
                        rx.button("2일", size="1",
                            variant=rx.cond(State.defensive_period == 2, "solid", "soft"),
                            on_click=State.set_defensive_period(2)),
                        rx.button("5일", size="1",
                            variant=rx.cond(State.defensive_period == 5, "solid", "soft"),
                            on_click=State.set_defensive_period(5)),
                        rx.button("30일", size="1",
                            variant=rx.cond(State.defensive_period == 30, "solid", "soft"),
                            on_click=State.set_defensive_period(30)),
                        rx.button("60일", size="1",
                            variant=rx.cond(State.defensive_period == 60, "solid", "soft"),
                            on_click=State.set_defensive_period(60)),
                        rx.button("120일", size="1",
                            variant=rx.cond(State.defensive_period == 120, "solid", "soft"),
                            on_click=State.set_defensive_period(120)),
                        spacing="2",
                        wrap="wrap",
                    ),
                    rx.hstack(
                        rx.text("Beta 상한: ", size="2", color="gray"),
                        rx.text(State.defensive_max_beta[0], size="2"),
                    ),
                    rx.slider(
                        min=0.3, max=1.0, step=0.1,
                        value=State.defensive_max_beta,
                        on_change=State.set_defensive_max_beta,
                        width="100%",
                    ),
                    rx.text("최소 시가총액", size="2", color="gray"),
                    rx.hstack(
                        rx.button("1조+", size="1",
                            variant=rx.cond(State.defensive_min_mktcap == 10_000, "solid", "soft"),
                            on_click=State.set_defensive_min_mktcap(10_000)),
                        rx.button("3천억+", size="1",
                            variant=rx.cond(State.defensive_min_mktcap == 3_000, "solid", "soft"),
                            on_click=State.set_defensive_min_mktcap(3_000)),
                        rx.button("전체", size="1",
                            variant=rx.cond(State.defensive_min_mktcap == 0, "solid", "soft"),
                            on_click=State.set_defensive_min_mktcap(0)),
                        spacing="2",
                    ),
                    rx.text("KOSPI/KOSDAQ만 지원 (약 1~2분 소요)", size="1", color="gray"),
                    spacing="3",
                    width="100%",
                ),
            ),
        ),

        rx.button(
            rx.cond(State.is_scanning, rx.spinner(size="2"), rx.text("스캔 실행")),
            on_click=State.run_scan,
            disabled=State.is_scanning,
            color_scheme="blue",
            width="100%",
        ),
        rx.cond(
            State.is_scanning & (State.scan_mode == "whale"),
            rx.button(
                rx.cond(
                    State.whale_stop_requested,
                    rx.hstack(rx.spinner(size="2"), rx.text("중단 중..."), spacing="2"),
                    rx.text("탐색 중단"),
                ),
                on_click=State.stop_whale_scan,
                disabled=State.whale_stop_requested,
                color_scheme="red",
                variant="soft",
                width="100%",
            ),
        ),
        rx.cond(
            State.scan_mode == "quant",
            rx.button("결과 저장", on_click=State.save_scan,
                disabled=State.scan_results.length() == 0,
                color_scheme="green", variant="soft", width="100%"),
            rx.button("결과 저장", on_click=State.save_whale_scan,
                disabled=State.whale_results.length() == 0,
                color_scheme="green", variant="soft", width="100%"),
        ),
        rx.cond(
            State.status_msg != "",
            rx.text(State.status_msg, size="1", color="gray"),
        ),

        spacing="4",
        width="100%",
    )


def sidebar() -> rx.Component:
    """데스크탑 고정 사이드바."""
    return rx.box(
        rx.vstack(
            rx.heading("QuantMaster Pro", size="5"),
            rx.text("Hybrid Quant & Technical Scanner", size="1", color="gray"),
            rx.divider(),
            sidebar_controls(),
            spacing="4",
            width="100%",
        ),
        display=rx.breakpoints(initial="none", sm="none", md="block"),
        width="240px",
        min_width="240px",
        padding="20px",
        border_right="1px solid var(--gray-4)",
        height="100vh",
        overflow_y="auto",
    )


def mobile_header() -> rx.Component:
    """모바일 상단 헤더 (햄버거 + 로고)."""
    return rx.box(
        rx.hstack(
            rx.icon_button(
                rx.icon("menu", size=20),
                on_click=State.toggle_sidebar,
                variant="ghost",
                size="3",
            ),
            rx.heading("QuantMaster Pro", size="4"),
            rx.spacer(),
            width="100%",
            align="center",
        ),
        display=rx.breakpoints(initial="flex", sm="flex", md="none"),
        padding_x="12px",
        padding_y="8px",
        border_bottom="1px solid var(--gray-4)",
        background="white",
        position="sticky",
        top="0",
        z_index="100",
    )


def mobile_drawer() -> rx.Component:
    """모바일 사이드바 드로어 오버레이."""
    return rx.cond(
        State.sidebar_open,
        rx.box(
            # 배경 딤처리 — 클릭 시 닫힘
            rx.box(
                on_click=State.toggle_sidebar,
                position="fixed",
                top="0", left="0", right="0", bottom="0",
                background="rgba(0,0,0,0.45)",
                z_index="200",
            ),
            # 드로어 패널
            rx.box(
                rx.vstack(
                    rx.hstack(
                        rx.heading("스캔 설정", size="4"),
                        rx.spacer(),
                        rx.icon_button(
                            rx.icon("x", size=18),
                            on_click=State.toggle_sidebar,
                            variant="ghost",
                            size="2",
                        ),
                        width="100%",
                        align="center",
                    ),
                    rx.divider(),
                    sidebar_controls(),
                    spacing="4",
                    width="100%",
                ),
                position="fixed",
                top="0", left="0", bottom="0",
                width="280px",
                background="white",
                z_index="201",
                overflow_y="auto",
                padding="20px",
                box_shadow="4px 0 24px rgba(0,0,0,0.18)",
            ),
            display=rx.breakpoints(initial="block", sm="block", md="none"),
        ),
    )


def scanner_tab() -> rx.Component:
    return rx.cond(
        State.scan_mode == "defensive",
        defensive_scanner_table(),
        rx.cond(
            State.scan_mode == "whale",
            whale_scanner_table(),
            rx.cond(
                State.scan_results.length() == 0,
                rx.center(
                    rx.text("왼쪽 사이드바에서 스캔을 실행하세요.", color="gray"),
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
    )


def defensive_scanner_table() -> rx.Component:
    """하락장 방어 스캔 결과 테이블."""
    return rx.cond(
        State.defensive_results.length() == 0,
        rx.center(
            rx.text("왼쪽 사이드바에서 하락방어 스캔을 실행하세요. (KOSPI/KOSDAQ)", color="gray"),
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
            rx.text("왼쪽 사이드바에서 세력 탐지 스캔을 실행하세요.", color="gray"),
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
            rx.divider(orientation="vertical", height="24px"),
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
            spacing="3", align="center", wrap="wrap",
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


def leaders_tab() -> rx.Component:
    """당일 주도주 탭 — 방법A/B 복합 점수 정렬."""
    return rx.vstack(
        # ── 컨트롤 바 ──────────────────────────────────────────
        rx.hstack(
            rx.heading("당일 주도주", size="4"),
            rx.spacer(),
            rx.select(
                ["KOSPI", "KOSDAQ", "US"],
                value=State.leaders_market,
                on_change=State.set_leaders_market,
                width="110px",
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
                # ── 행2: 종류 필터 + 종가매매 후보 ─────────────────
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
                    rx.separator(orientation="vertical", size="1"),
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
        # ── 에러 ────────────────────────────────────────────────
        rx.cond(
            State.leaders_error != "",
            rx.callout.root(
                rx.callout.text(State.leaders_error),
                color_scheme="red",
                variant="soft",
            ),
        ),
        # ── 미조회 안내 ─────────────────────────────────────────
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
                rx.callout.root(
                    rx.callout.text("'조회' 버튼을 눌러 오늘의 주도주를 가져오세요."),
                    color_scheme="blue",
                    variant="soft",
                ),
            ),
            # ── 데이터 뷰 (모바일 카드 + 데스크탑 테이블) ────────
            rx.vstack(
                # 모바일 카드
                rx.box(
                    rx.foreach(
                        State.leaders_data,
                        lambda h: rx.card(
                        rx.vstack(
                            rx.hstack(
                                rx.badge(h["rank"], variant="soft", color_scheme="gray"),
                                rx.text(h["name"], weight="bold", size="3"),
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


def main_content() -> rx.Component:
    return rx.tabs.root(
        rx.tabs.list(
            rx.tabs.trigger("시장모멘텀", value="momentum"),
            rx.tabs.trigger("당일주도주", value="leaders"),
            rx.tabs.trigger("스캐너", value="scanner"),
            rx.tabs.trigger("분석", value="analysis"),
            rx.tabs.trigger("종목조회", value="lookup"),
            rx.tabs.trigger("포트폴리오", value="portfolio"),
            rx.tabs.trigger("히스토리", value="history"),
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
        value=State.active_tab,
        on_change=State.set_tab,
        width="100%",
    )


def index() -> rx.Component:
    return rx.box(
        mobile_header(),
        mobile_drawer(),
        rx.flex(
            sidebar(),
            rx.box(
                rx.box(
                    main_content(),
                    padding=rx.breakpoints(initial="12px", sm="16px", md="24px"),
                ),
                flex="1",
                overflow_y="auto",
                height=rx.breakpoints(initial="calc(100vh - 53px)", sm="calc(100vh - 53px)", md="100vh"),
            ),
            direction="row",
            width="100%",
        ),
        min_height="100vh",
        width="100%",
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
app.add_page(index, title="QuantMaster Pro", on_load=State.load_holdings_from_db)
