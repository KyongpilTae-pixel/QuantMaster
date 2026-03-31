import pandas as pd
from utils.data_loader import QuantDataLoader
from utils.indicators import TechnicalIndicators


# 완화 단계 정의: (PBR 한도, GPA 최소 백분위, MFI 최소값, OBV 필수 여부)
_RELAXATION_STEPS = [
    # stage,  pbr_max, gpa_min, mfi_min, require_obv
    (1,       1.2,     0.6,     50,      True),   # 원본 조건
    (2,       1.5,     0.4,     45,      True),   # PBR/GPA 완화
    (3,       2.0,     0.2,     45,      True),   # 추가 완화
    (4,       2.0,     0.0,     45,      False),  # OBV 조건 제거
    (5,       2.0,     0.0,     40,      False),  # MFI 추가 완화
]

_STEP_LABELS = {
    1: "원본",
    2: "PBR완화",
    3: "GPA완화",
    4: "OBV제외",
    5: "MFI완화",
}


class QuantScanner:
    def run_advanced_scan(
        self,
        target_pbr: float = 1.2,
        vwap_period: int = 120,
        min_count: int = 10,
        market: str = "KOSPI",
    ) -> pd.DataFrame:
        """
        3단계 하이브리드 스캔 + 자동 임계값 완화:
          1단계 (Quant)     : PBR <= target_pbr & GPA_Score >= gpa_min
          2단계 (Technical) : 종가 > VWAP_{vwap_period}
          3단계 (Momentum)  : MFI > mfi_min [& OBV > OBV_Sig]

        결과가 min_count 미만이면 완화 단계를 순차적으로 적용.
        PBR 한도는 사용자 설정값(target_pbr)과 단계별 pbr_max 중 큰 값 사용.
        """
        loader = QuantDataLoader()
        stocks = loader.get_market_snapshot(market=market)

        if stocks.empty:
            return pd.DataFrame()

        final_candidates: list[dict] = []
        seen_symbols: set[str] = set()

        for step, pbr_max, gpa_min, mfi_min, require_obv in _RELAXATION_STEPS:
            if len(final_candidates) >= min_count:
                break

            # 사용자가 지정한 PBR 한도와 단계별 한도 중 큰 값 적용
            effective_pbr = max(target_pbr, pbr_max) if step > 1 else target_pbr

            filtered = stocks[
                (stocks["PBR"] <= effective_pbr)
                & (stocks["GPA_Score"] >= gpa_min)
            ].sort_values("PBR").head(60)

            for _, row in filtered.iterrows():
                if len(final_candidates) >= min_count:
                    break
                if row["Symbol"] in seen_symbols:
                    continue

                try:
                    df = loader.get_ohlcv(row["Symbol"])
                    if len(df) < vwap_period + 20:
                        continue

                    df = TechnicalIndicators.calculate_all(df, [vwap_period])
                    curr = df.dropna().iloc[-1]

                    vwap_col = f"VWAP_{vwap_period}"
                    vwap_ok = curr["Close"] > curr[vwap_col]
                    mfi_ok = curr["MFI"] > mfi_min
                    obv_ok = curr["OBV"] > curr["OBV_Sig"]

                    if vwap_ok and mfi_ok and (obv_ok or not require_obv):
                        seen_symbols.add(row["Symbol"])
                        final_candidates.append(
                            {
                                "Name": row["Name"],
                                "Symbol": row["Symbol"],
                                "PBR": round(row["PBR"], 2),
                                "MFI": round(curr["MFI"], 1),
                                "OBV_OK": obv_ok,
                                "VWAP_Price": round(curr[vwap_col], 0),
                                "Close": round(curr["Close"], 0),
                                "VWAP_Gap": round(
                                    (curr["Close"] - curr[vwap_col])
                                    / curr[vwap_col] * 100,
                                    1,
                                ),
                                # 적용된 임계값 정보
                                "Applied_PBR": effective_pbr,
                                "Applied_GPA": gpa_min,
                                "Applied_MFI": mfi_min,
                                "Applied_OBV": require_obv,
                                "Condition": _STEP_LABELS[step],
                            }
                        )
                except Exception:
                    continue

        return pd.DataFrame(final_candidates).head(min_count)
