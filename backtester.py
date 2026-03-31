import pandas as pd
import numpy as np
from utils.data_loader import QuantDataLoader
from utils.indicators import TechnicalIndicators


class Backtester:
    """
    단일 종목 백테스트 (VWAP 돌파 전략):
      - 진입: Close > VWAP & MFI > 50 & OBV > OBV_Sig
      - 청산: Close < VWAP (추세 이탈)
    """

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

        buy_sig = (
            (df["Close"] > df[vwap_col])
            & (df["MFI"] > 50)
            & (df["OBV"] > df["OBV_Sig"])
        )
        sell_sig = df["Close"] < df[vwap_col]

        trades, equity_curve = self._simulate(
            df, buy_sig, sell_sig, vwap_col, initial_capital
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
    ) -> tuple[list, list]:
        capital = float(initial_capital)
        position = 0
        entry_price = 0.0
        entry_date = None
        trades: list[dict] = []
        equity_curve: list[float] = [capital]
        in_position = False

        for i in range(1, len(df)):
            price = float(df["Close"].iloc[i])
            date = df.index[i]

            if not in_position and buy_sig.iloc[i - 1]:
                shares = int(capital // price)
                if shares > 0:
                    entry_price = price
                    position = shares
                    capital -= shares * price
                    entry_date = date
                    in_position = True

            elif in_position and sell_sig.iloc[i]:
                pnl = (price - entry_price) * position
                ret = (price - entry_price) / entry_price * 100
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
                capital += position * price
                position = 0
                in_position = False

            current_equity = capital + (position * price if in_position else 0.0)
            equity_curve.append(current_equity)

        # 미청산 포지션 강제 청산
        if in_position:
            final_price = float(df["Close"].iloc[-1])
            pnl = (final_price - entry_price) * position
            ret = (final_price - entry_price) / entry_price * 100
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
