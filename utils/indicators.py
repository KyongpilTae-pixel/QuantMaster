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

        return df


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
