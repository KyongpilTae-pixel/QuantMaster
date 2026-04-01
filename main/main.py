"""
QuantMaster Pro v2.0 — Reflex UI
Hybrid Quant & Technical Breakout Scanner
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
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
    pbr: float = 0.0
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


class BacktestSummary(BaseModel):
    total_return: float = 0.0
    mdd: float = 0.0
    win_rate: float = 0.0
    avg_return: float = 0.0
    sharpe: float = 0.0
    trade_count: int = 0


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
    buy_msg: str = ""
    sell_msg: str = ""

    # Backtest results
    bt_summary: BacktestSummary = BacktestSummary()
    equity_data: List[dict] = []
    trades_data: List[dict] = []

    # 분석 차트 데이터 (종가 + VWAP)
    price_chart_data: List[dict] = []
    is_loading_chart: bool = False

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

    def set_tab(self, tab: str):
        self.active_tab = tab

    async def select_stock(self, name: str):
        self.selected_name = name
        target = next((r for r in self.scan_results if r.name == name), None)
        if not target:
            return

        buy, sell = InvestmentReasoning.generate_report(
            target.name, target.pbr, int(self.vwap_period),
            target.mfi, target.vwap_price, target.currency,
        )
        self.buy_msg = buy
        self.sell_msg = sell
        self.bt_summary = BacktestSummary()
        self.equity_data = []
        self.trades_data = []
        self.price_chart_data = []
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
            df = TechnicalIndicators.calculate_all(df, [vwap, 20, 60])
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
                }
                for d, row in display_df.iterrows()
            ]
        except Exception:
            pass
        finally:
            self.is_loading_chart = False
        yield

    # ------------------------------------------------------------------
    # Async event handlers
    # ------------------------------------------------------------------

    async def run_scan(self):
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
                    pbr=float(row["PBR"]),
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
        target = next(
            (r for r in self.scan_results if r.name == self.selected_name), None
        )
        if not target:
            self.status_msg = "종목을 먼저 선택하세요."
            return

        self.is_backtesting = True
        self.status_msg = f"{target.name} 백테스트 실행 중..."
        yield

        try:
            bt = Backtester()
            result = await asyncio.to_thread(
                bt.run,
                target.symbol,
                target.name,
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
                self.status_msg = "백테스트 완료"
                self.active_tab = "backtest"
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


def sidebar() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.heading("QuantMaster Pro", size="5"),
            rx.text("Hybrid Quant & Technical Scanner", size="1", color="gray"),
            rx.divider(),

            rx.text("시장", size="2", color="gray"),
            rx.select.root(
                rx.select.trigger(placeholder="시장 선택"),
                rx.select.content(
                    rx.select.group(
                        rx.select.label("한국"),
                        rx.select.item("KOSPI", value="KOSPI"),
                        rx.select.item("KOSDAQ", value="KOSDAQ"),
                    ),
                    rx.select.separator(),
                    rx.select.group(
                        rx.select.label("미국"),
                        rx.select.item("S&P 500", value="SP500"),
                        rx.select.item("NASDAQ", value="NASDAQ"),
                    ),
                ),
                value=State.market,
                on_change=State.set_market,
                width="100%",
            ),

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

            rx.button(
                rx.cond(
                    State.is_scanning,
                    rx.spinner(size="2"),
                    rx.text("스캔 실행"),
                ),
                on_click=State.run_scan,
                disabled=State.is_scanning,
                color_scheme="blue",
                width="100%",
            ),

            rx.cond(
                State.status_msg != "",
                rx.text(State.status_msg, size="1", color="gray"),
            ),

            spacing="4",
            width="100%",
        ),
        width="240px",
        min_width="240px",
        padding="20px",
        border_right="1px solid var(--gray-4)",
        height="100vh",
        overflow_y="auto",
    )


def scanner_tab() -> rx.Component:
    return rx.cond(
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
        rx.center(rx.spinner(size="3"), height="200px"),
        rx.cond(
            State.price_chart_data.length() > 0,
            rx.vstack(
                rx.hstack(
                    rx.text("가격 차트", weight="bold", size="2"),
                    rx.badge("종가", color_scheme="blue"),
                    rx.badge("VWAP " + State.vwap_period + "일", color_scheme="amber"),
                    rx.badge("TWAP20", color_scheme="green"),
                    rx.badge("TWAP60", color_scheme="red"),
                    spacing="2",
                    align_items="center",
                ),
                rx.recharts.line_chart(
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
            ),
            rx.box(),
        ),
    )


def analysis_tab() -> rx.Component:
    return rx.cond(
        State.selected_name != "",
        rx.vstack(
            rx.heading(State.selected_name, size="5"),
            # 1. 매수 근거
            rx.box(
                rx.text("매수 근거", weight="bold", color="green", size="2"),
                rx.text(State.buy_msg, size="2"),
                padding="16px",
                border_radius="8px",
                background="var(--green-2)",
                border="1px solid var(--green-6)",
                width="100%",
            ),
            # 1-1. MFI / OBV 지표 설명
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
            # 2. 매도 가이드
            rx.box(
                rx.text("매도 가이드", weight="bold", color="red", size="2"),
                rx.text(State.sell_msg, size="2"),
                padding="16px",
                border_radius="8px",
                background="var(--red-2)",
                border="1px solid var(--red-6)",
                width="100%",
            ),
            # 3. 차트
            price_chart(),
            # 4 & 5. 적용된 스캔 조건 / 실제 측정값
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
            rx.button(
                rx.cond(State.is_backtesting, rx.spinner(size="2"), rx.text("백테스트 실행")),
                on_click=State.run_backtest,
                disabled=State.is_backtesting,
                color_scheme="violet",
            ),
            width="100%",
            spacing="4",
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


def backtest_tab() -> rx.Component:
    s = State.bt_summary
    return rx.cond(
        State.bt_summary.trade_count > 0,
        rx.vstack(
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
        rx.center(
            rx.text("분석 탭에서 백테스트를 실행하세요.", color="gray"),
            height="150px",
        ),
    )


def main_content() -> rx.Component:
    return rx.tabs.root(
        rx.tabs.list(
            rx.tabs.trigger("스캐너", value="scanner"),
            rx.tabs.trigger("분석", value="analysis"),
            rx.tabs.trigger("백테스트", value="backtest"),
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
            rx.box(backtest_tab(), padding_top="16px"),
            value="backtest",
        ),
        value=State.active_tab,
        on_change=State.set_tab,
        width="100%",
    )


def index() -> rx.Component:
    return rx.flex(
        sidebar(),
        rx.box(
            rx.box(main_content(), padding="24px"),
            flex="1",
            overflow_y="auto",
            height="100vh",
        ),
        direction="row",
        width="100%",
        min_height="100vh",
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
app.add_page(index, title="QuantMaster Pro")
