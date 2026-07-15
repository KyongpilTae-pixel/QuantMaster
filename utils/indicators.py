import pandas as pd
import numpy as np


class TechnicalIndicators:
    @staticmethod
    def calculate_all(df: pd.DataFrame, windows: list[int] = [20, 60, 120]) -> pd.DataFrame:
        df = df.copy()
        tp = (df["High"] + df["Low"] + df["Close"]) / 3
        pv = tp * df["Volume"]

        for w in windows:
            df[f"VWAP_{w}"] = pv.rolling(window=w).sum() / df["Volume"].rolling(window=w).sum()
            df[f"TWAP_{w}"] = tp.rolling(window=w).mean()
            df[f"SMA_{w}"] = df["Close"].rolling(window=w).mean()

        # MFI (Money Flow Index)
        mf = tp * df["Volume"]
        pos_mf = mf.where(tp > tp.shift(1), 0).rolling(window=14).sum()
        neg_mf = mf.where(tp < tp.shift(1), 0).rolling(window=14).sum()
        # When neg_mf=0 and pos_mf>0 → MFI=100; when both=0 (flat) → MFI=50
        with np.errstate(divide="ignore", invalid="ignore"):
            mfr = np.where(
                neg_mf == 0,
                np.where(pos_mf == 0, 1.0, np.inf),
                pos_mf.values / neg_mf.values,
            )
        df["MFI"] = 100 - (100 / (1 + mfr))

        # OBV (On-Balance Volume)
        df["OBV"] = (np.sign(df["Close"].diff()) * df["Volume"]).fillna(0).cumsum()
        df["OBV_Sig"] = df["OBV"].rolling(window=20).mean()

        # RSI14
        df["RSI14"] = TechnicalIndicators.calc_rsi(df["Close"], 14)

        # Bollinger Bands (20일, 2σ) — 가격 차트 오버레이용
        bb_u, _bb_m, bb_l = TechnicalIndicators.calc_bb(df["Close"], 20, 2.0)
        df["BB_upper"] = bb_u
        df["BB_lower"] = bb_l

        # ATR14 (Average True Range) — 손절 계산용
        prev_close = df["Close"].shift(1)
        tr = pd.concat([
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"]  - prev_close).abs(),
        ], axis=1).max(axis=1)
        df["ATR14"] = tr.rolling(window=14).mean()

        return df


    @staticmethod
    def calc_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
        """RSI(period) 시리즈 반환. 순수 상승 → 100, 순수 하락 → 0."""
        delta = closes.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        with np.errstate(divide="ignore", invalid="ignore"):
            rs = np.where(loss == 0, np.inf, gain.values / loss.values)
        return pd.Series(100 - (100 / (1 + rs)), index=closes.index)

    @staticmethod
    def calc_bb(
        closes: pd.Series,
        period: int = 20,
        std_mult: float = 2.0,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Bollinger Bands (upper, mid, lower) 반환."""
        mid   = closes.rolling(period).mean()
        std   = closes.rolling(period).std(ddof=1)
        return mid + std_mult * std, mid, mid - std_mult * std


def compute_vwap(df: pd.DataFrame, period: int = 20) -> float | None:
    """DataFrame의 마지막 행 VWAP(period) 값을 반환. 데이터 부족 시 None."""
    if len(df) < period:
        return None
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    pv = (tp * df["Volume"]).rolling(window=period).sum()
    vol = df["Volume"].rolling(window=period).sum()
    vwap_series = pv / vol
    val = vwap_series.iloc[-1]
    return float(val) if pd.notna(val) else None
