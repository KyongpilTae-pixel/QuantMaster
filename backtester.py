import pandas as pd
import numpy as np
from utils.data_loader import QuantDataLoader
from utils.indicators import TechnicalIndicators


class Backtester:
    """
    단일 종목 백테스트 (VWAP 돌파 전략):
      - 진입: Close > VWAP & MFI > 50 & OBV > OBV_Sig
      - 청산: Close < VWAP (추세 이탈)
      - 비용: KR 거래세 0.18% + 수수료 0.015% + 슬리피지 0.05% (양방향)
              US 거래세 없음 + 수수료 0.005% + 슬리피지 0.05%
    """

    # 한국 거래 비용 (매수 + 매도 합산)
    _KR_TAX   = 0.0018   # 거래세 (매도만)
    _KR_FEE   = 0.00015  # 수수료 (양방향 각)
    _KR_SLIP  = 0.0005   # 슬리피지 (양방향 각)

    # 미국 거래 비용
    _US_FEE   = 0.00005  # 수수료 (양방향 각)
    _US_SLIP  = 0.0005   # 슬리피지 (양방향 각)

    def __init__(self):
        self.loader = QuantDataLoader()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def run(
        self,
        symbol: str,
        name: str,
        vwap_period: int = 120,
        initial_capital: int = 10_000_000,
    ) -> dict | None:
        df = self.loader.get_ohlcv(symbol, lookback_days=600)
        if len(df) < vwap_period + 50:
            return None

        df = TechnicalIndicators.calculate_all(df, [vwap_period])
        df = df.dropna().copy()

        vwap_col = f"VWAP_{vwap_period}"

        # 거래 비용 계수 (is_us: US 종목 여부)
        is_us = symbol.endswith((".US", ".OQ")) or (
            symbol.isalpha() and len(symbol) <= 5
        )
        if is_us:
            buy_cost  = self._US_FEE + self._US_SLIP
            sell_cost = self._US_FEE + self._US_SLIP
        else:
            buy_cost  = self._KR_FEE + self._KR_SLIP
            sell_cost = self._KR_TAX + self._KR_FEE + self._KR_SLIP

        buy_sig = (
            (df["Close"] > df[vwap_col])
            & (df["MFI"] > 50)
            & (df["OBV"] > df["OBV_Sig"])
        )
        sell_sig = df["Close"] < df[vwap_col]

        trades, equity_curve = self._simulate(
            df, buy_sig, sell_sig, vwap_col, initial_capital,
            buy_cost, sell_cost,
        )

        equity_series = pd.Series(
            equity_curve, index=df.index[: len(equity_curve)]
        )

        trades_df = pd.DataFrame(trades)
        win_rate = avg_return = 0.0
        if len(trades_df) > 0:
            win_rate = (trades_df["Return"] > 0).mean() * 100
            avg_return = trades_df["Return"].mean()

        final_capital = equity_curve[-1]
        total_return = (final_capital - initial_capital) / initial_capital * 100
        mdd = self._calc_mdd(equity_series) * 100
        sharpe = self._calc_sharpe(equity_series)
        total_cost_pct = (buy_cost + sell_cost) * 100

        return {
            "Symbol": symbol,
            "Name": name,
            "Total_Return": total_return,
            "MDD": mdd,
            "Win_Rate": win_rate,
            "Avg_Return": avg_return,
            "Sharpe": sharpe,
            "Trades": len(trades_df),
            "Equity_Curve": equity_series,
            "Trades_DF": trades_df,
            "OHLCV": df,
            "VWAP_Col": vwap_col,
            "Cost_Per_Trade_Pct": round(total_cost_pct, 3),
        }

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------
    def _simulate(
        self,
        df: pd.DataFrame,
        buy_sig: pd.Series,
        sell_sig: pd.Series,
        vwap_col: str,
        initial_capital: int,
        buy_cost: float = 0.0,
        sell_cost: float = 0.0,
    ) -> tuple[list, list]:
        capital = float(initial_capital)
        position = 0
        entry_price = 0.0
        entry_cost_total = 0.0
        entry_date = None
        trades: list[dict] = []
        equity_curve: list[float] = [capital]
        in_position = False

        for i in range(1, len(df)):
            price = float(df["Close"].iloc[i])
            date = df.index[i]

            if not in_position and buy_sig.iloc[i - 1]:
                effective_buy = price * (1 + buy_cost)
                shares = int(capital // effective_buy)
                if shares > 0:
                    cost = shares * effective_buy
                    entry_price = price
                    entry_cost_total = cost
                    position = shares
                    capital -= cost
                    entry_date = date
                    in_position = True

            elif in_position and sell_sig.iloc[i]:
                proceeds = position * price * (1 - sell_cost)
                pnl = proceeds - entry_cost_total
                ret = pnl / entry_cost_total * 100
                trades.append(
                    {
                        "Entry": str(entry_date.date()),
                        "Exit": str(date.date()),
                        "Entry_Price": entry_price,
                        "Exit_Price": price,
                        "Shares": position,
                        "PnL": round(pnl, 0),
                        "Return": round(ret, 2),
                    }
                )
                capital += proceeds
                position = 0
                in_position = False

            current_equity = capital + (position * price if in_position else 0.0)
            equity_curve.append(current_equity)

        # 미청산 포지션 강제 청산
        if in_position:
            final_price = float(df["Close"].iloc[-1])
            proceeds = position * final_price * (1 - sell_cost)
            pnl = proceeds - entry_cost_total
            ret = pnl / entry_cost_total * 100
            trades.append(
                {
                    "Entry": str(entry_date.date()),
                    "Exit": str(df.index[-1].date()),
                    "Entry_Price": entry_price,
                    "Exit_Price": final_price,
                    "Shares": position,
                    "PnL": round(pnl, 0),
                    "Return": round(ret, 2),
                }
            )

        return trades, equity_curve

    # ------------------------------------------------------------------
    # Monte Carlo 시뮬레이션
    # ------------------------------------------------------------------
    @staticmethod
    def run_monte_carlo(
        trades: list[dict],
        initial_capital: float = 10_000_000,
        n_sim: int = 1000,
    ) -> dict:
        """
        매매 결과를 n_sim회 무작위 재배열 → 결과 분포 계산.
        반환: p5/p50/p95 최종 자본, VaR5%, CVaR1%, 파산확률%, 퍼센타일 곡선
        """
        if not trades:
            return {"error": "매매 내역이 없습니다."}

        returns = [t["Return"] / 100.0 for t in trades]
        n_trades = len(returns)
        rng = np.random.default_rng(seed=42)

        # n_sim × (n_trades+1) 자본금 곡선 행렬
        sim_curves = np.empty((n_sim, n_trades + 1))
        sim_curves[:, 0] = initial_capital
        for s in range(n_sim):
            idxs = rng.integers(0, n_trades, size=n_trades)
            factors = np.array([1.0 + returns[i] for i in idxs])
            sim_curves[s, 1:] = initial_capital * np.cumprod(factors)

        final_vals = sim_curves[:, -1]
        p5  = float(np.percentile(final_vals, 5))
        p50 = float(np.percentile(final_vals, 50))
        p95 = float(np.percentile(final_vals, 95))

        bankruptcy_pct = float((final_vals < initial_capital * 0.5).mean() * 100)
        var5_pct = float((initial_capital - p5) / initial_capital * 100)

        cvar_cut = np.percentile(final_vals, 1)
        tail = final_vals[final_vals <= cvar_cut]
        cvar_val = float(tail.mean()) if len(tail) > 0 else p5
        cvar1_pct = float((initial_capital - cvar_val) / initial_capital * 100)

        # 차트용: 매 거래 단계별 퍼센타일 포인트 (최대 200 포인트로 다운샘플)
        step = max(1, (n_trades + 1) // 200)
        indices = list(range(0, n_trades + 1, step))
        p5_curve  = np.percentile(sim_curves[:, indices], 5,  axis=0)
        p50_curve = np.percentile(sim_curves[:, indices], 50, axis=0)
        p95_curve = np.percentile(sim_curves[:, indices], 95, axis=0)

        chart_data = [
            {
                "trade": indices[i],
                "p5":  round(float(p5_curve[i]),  0),
                "p50": round(float(p50_curve[i]), 0),
                "p95": round(float(p95_curve[i]), 0),
            }
            for i in range(len(indices))
        ]

        return {
            "p5":  round(p5,  0),
            "p50": round(p50, 0),
            "p95": round(p95, 0),
            "initial_capital": initial_capital,
            "bankruptcy_pct": round(bankruptcy_pct, 1),
            "var5_pct":  round(var5_pct, 1),
            "cvar1_pct": round(cvar1_pct, 1),
            "chart_data": chart_data,
            "n_sim":    n_sim,
            "n_trades": n_trades,
        }

    @staticmethod
    def _calc_mdd(equity: pd.Series) -> float:
        peak = equity.cummax()
        return ((equity - peak) / peak).min()

    @staticmethod
    def _calc_sharpe(equity: pd.Series, risk_free: float = 0.03) -> float:
        daily_ret = equity.pct_change().dropna()
        if daily_ret.std() == 0:
            return 0.0
        excess = daily_ret.mean() - risk_free / 252
        return round(excess / daily_ret.std() * np.sqrt(252), 2)
