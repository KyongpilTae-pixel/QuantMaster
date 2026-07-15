"""글로벌 시장 모멘텀 스캐너 — 5가지 전략 통합 분석."""

import math
from datetime import datetime, timedelta

import FinanceDataReader as fdr
import numpy as np
import pandas as pd

_ASSETS = [
    {"key": "kr",   "name": "한국 (KOSPI)", "code": "KS11"},
    {"key": "us",   "name": "미국 (S&P500)", "code": "SPY"},
    {"key": "cn",   "name": "중국 (상하이)", "code": "SSEC"},
    {"key": "jp",   "name": "일본 (닛케이)", "code": "N225"},
    {"key": "bond", "name": "채권 (TLT)",    "code": "TLT"},
    {"key": "gold", "name": "금 (GLD)",      "code": "GLD"},
]

# 기간 레이블 → 거래일 수
_PERIOD_DAYS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}


def _fetch_prices(code: str) -> pd.Series | None:
    """최근 ~300 거래일 종가 반환 (MA200·변동성 계산에 충분한 버퍼)."""
    try:
        end = datetime.today()
        start = end - timedelta(days=700)
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if df.empty or "Close" not in df.columns:
            return None
        return df["Close"].dropna()
    except Exception:
        return None


def _period_ret(prices: pd.Series, days: int) -> float | None:
    if prices is None or len(prices) < days + 1:
        return None
    return round(float(prices.iloc[-1] / prices.iloc[-(days + 1)] - 1) * 100, 2)


def fetch_momentum_data() -> dict:
    """
    4가지 전략 결과 반환:
      단순 모멘텀 / VAA 모멘텀 / MA200 필터 / 역변동성 배분

    Returns dict with keys:
      rows, momentum_rec_name/key/desc,
      vaa_rec_name/key/desc, ma_rec_name/key/desc,
      invvol_rec_desc, error
    """
    # ── 1. 가격 데이터 수집 ─────────────────────────────────────
    price_map: dict[str, pd.Series | None] = {
        a["key"]: _fetch_prices(a["code"]) for a in _ASSETS
    }

    rows = []
    for asset in _ASSETS:
        key, name = asset["key"], asset["name"]
        prices = price_map[key]
        row: dict = {"key": key, "name": name}

        # ── 수익률 ──────────────────────────────────────────────
        for lbl, days in _PERIOD_DAYS.items():
            ret = _period_ret(prices, days)
            row[f"ret_{lbl}"] = ret
            row[f"ret_{lbl}_str"] = f"{ret:+.2f}%" if ret is not None else "-"
            row[f"pos_{lbl}"] = ret is not None and ret > 0

        # ── VAA 점수 = 12×1m + 4×3m + 2×6m + 1×12m ─────────────
        r1, r3, r6, r12 = (row.get(f"ret_{k}") for k in ("1m", "3m", "6m", "12m"))
        if all(v is not None for v in (r1, r3, r6, r12)):
            vaa = round(12 * r1 + 4 * r3 + 2 * r6 + r12, 1)
        else:
            vaa = None
        row["vaa_score"] = vaa
        row["vaa_score_str"] = f"{vaa:+.1f}" if vaa is not None else "-"
        row["vaa_positive"] = vaa is not None and vaa > 0

        # ── MA200 신호 ───────────────────────────────────────────
        if prices is not None and len(prices) >= 200:
            current = float(prices.iloc[-1])
            ma200 = float(prices.tail(200).mean())
            above = current > ma200
            row["close_str"] = f"{current:,.2f}"
            row["ma200_str"] = f"{ma200:,.2f}"
            row["above_ma"] = above
            row["ma_signal_str"] = "위 ↑" if above else "아래 ↓"
        else:
            row["close_str"] = row["ma200_str"] = "-"
            row["above_ma"] = False
            row["ma_signal_str"] = "-"

        # ── 60일 연환산 변동성 ────────────────────────────────────
        if prices is not None and len(prices) >= 61:
            vol = float(prices.pct_change().dropna().tail(60).std() * math.sqrt(252) * 100)
            row["vol_val"] = vol
            row["vol_str"] = f"{vol:.1f}%"
        else:
            row["vol_val"] = None
            row["vol_str"] = "-"

        rows.append(row)

    # ── 2. 단순 모멘텀 추천 ─────────────────────────────────────
    period_winners: dict[str, str] = {}
    for lbl in ("1m", "3m", "6m", "12m"):
        best_key, best_ret = "cash", 0.0
        for r in rows:
            v = r.get(f"ret_{lbl}")
            if v is not None and v > best_ret:
                best_ret, best_key = v, r["key"]
        period_winners[lbl] = best_key

    win_counts: dict[str, int] = {}
    for w in period_winners.values():
        win_counts[w] = win_counts.get(w, 0) + 1
    max_w = max(win_counts.values())
    cands = [k for k, v in win_counts.items() if v == max_w]
    mom_key = cands[0] if len(cands) == 1 else period_winners["12m"]
    mom_name = next((r["name"] for r in rows if r["key"] == mom_key), "현금 보유")
    wins = win_counts.get(mom_key, 0)
    if mom_key == "cash":
        mom_name, mom_desc = "현금 보유", "전 기간 마이너스"
    elif wins == 4:
        mom_desc = "4개 기간 모두 1위"
    elif wins == 3:
        mom_desc = "3개 기간 1위"
    elif wins == 2:
        mom_desc = "2개 기간 1위"
    else:
        r12_str = next((r["ret_12m_str"] for r in rows if r["key"] == mom_key), "")
        mom_desc = f"12M {r12_str}"

    # ── 3. VAA 추천 ──────────────────────────────────────────────
    valid_vaa = sorted(
        [(r["key"], r["name"], r["vaa_score"]) for r in rows if r["vaa_score"] is not None],
        key=lambda x: x[2], reverse=True,
    )
    if valid_vaa and valid_vaa[0][2] > 0:
        vaa_key, vaa_name, vaa_top = valid_vaa[0]
        vaa_desc = f"VAA 점수 {vaa_top:+.1f} (1위)"
    else:
        vaa_key, vaa_name = "cash", "현금 보유"
        vaa_desc = "전 자산 점수 마이너스"

    # ── 4. MA200 필터 추천 ────────────────────────────────────────
    eligible = [r for r in rows if r["above_ma"] and r.get("ret_12m") is not None]
    if eligible:
        best_ma = max(eligible, key=lambda r: r["ret_12m"])
        ma_key = best_ma["key"]
        ma_name = best_ma["name"]
        ma_desc = f"MA200 위 자산 중 12M {best_ma['ret_12m_str']} 1위"
    else:
        ma_key, ma_name = "cash", "현금 보유"
        ma_desc = "MA200 위 자산 없음"

    # ── 5. 역변동성 배분 ──────────────────────────────────────────
    valid_vol = [r for r in rows if r["vol_val"] is not None and r["vol_val"] > 0]
    if valid_vol:
        total_inv = sum(1 / r["vol_val"] for r in valid_vol)
        for r in valid_vol:
            w = round(1 / r["vol_val"] / total_inv * 100, 1)
            r["inv_vol_weight"] = w
            r["inv_vol_weight_str"] = f"{w:.1f}%"
        for r in rows:
            if "inv_vol_weight" not in r:
                r["inv_vol_weight"] = 0.0
                r["inv_vol_weight_str"] = "-"
        top3 = sorted(valid_vol, key=lambda r: r["inv_vol_weight"], reverse=True)[:3]
        invvol_key = top3[0]["key"]
        invvol_desc = "  /  ".join(
            f"{r['name'].split('(')[0].strip()} {r['inv_vol_weight_str']}" for r in top3
        )
    else:
        for r in rows:
            r["inv_vol_weight"] = 0.0
            r["inv_vol_weight_str"] = "-"
        invvol_key = "cash"
        invvol_desc = "데이터 부족"

    # ── 6. Risk Parity 배분 (공분산 행렬 기반 위험 균형) ──────────
    rp_key = "cash"
    rp_desc = "데이터 부족"
    try:
        from scipy.optimize import minimize as _minimize

        ret_series = []
        rp_keys = []
        for r in rows:
            prices = price_map[r["key"]]
            if prices is not None and len(prices) >= 61:
                s = prices.pct_change().dropna().tail(60).values
                ret_series.append(s)
                rp_keys.append(r["key"])

        if len(rp_keys) >= 2:
            min_len = min(len(s) for s in ret_series)
            R = np.array([s[:min_len] for s in ret_series]).T  # (T, N)
            cov = np.cov(R, rowvar=False)
            n = len(rp_keys)

            def _obj(w):
                port_var = float(w @ cov @ w)
                if port_var <= 0:
                    return 1e9
                rc = w * (cov @ w) / port_var
                target = np.ones(n) / n
                return float(np.sum((rc - target) ** 2))

            w0 = np.ones(n) / n
            bounds = [(0.01, 1.0)] * n
            cons = [{"type": "eq", "fun": lambda w: float(np.sum(w)) - 1}]
            res = _minimize(_obj, w0, bounds=bounds, constraints=cons, method="SLSQP",
                            options={"ftol": 1e-9, "maxiter": 500})
            rp_w = res.x / res.x.sum()

            for r in rows:
                if r["key"] in rp_keys:
                    idx = rp_keys.index(r["key"])
                    w = round(float(rp_w[idx]) * 100, 1)
                    r["rp_weight"] = w
                    r["rp_weight_str"] = f"{w:.1f}%"
                else:
                    r["rp_weight"] = 0.0
                    r["rp_weight_str"] = "-"

            top3_rp = sorted(
                [r for r in rows if r.get("rp_weight", 0) > 0],
                key=lambda r: r["rp_weight"], reverse=True,
            )[:3]
            rp_key = top3_rp[0]["key"] if top3_rp else "cash"
            rp_desc = "  /  ".join(
                f"{r['name'].split('(')[0].strip()} {r['rp_weight_str']}" for r in top3_rp
            )
        else:
            raise ValueError("not enough assets")

    except Exception:
        # scipy 미설치 또는 최적화 실패 → 역변동성으로 대체
        for r in rows:
            r["rp_weight"] = r.get("inv_vol_weight", 0.0)
            r["rp_weight_str"] = r.get("inv_vol_weight_str", "-")
        rp_key = invvol_key
        rp_desc = invvol_desc + " (역변동성 대체)"

    # ── 7. bool 플래그 (rx.foreach 내 비교 불가 우회) ─────────────
    for r in rows:
        for lbl in ("1m", "3m", "6m", "12m"):
            r[f"win_{lbl}"] = (period_winners.get(lbl) == r["key"])
        r["is_recommended"] = (r["key"] == mom_key)          # 기존 호환
        r["is_rec_momentum"] = (r["key"] == mom_key)
        r["is_rec_vaa"] = (r["key"] == vaa_key)
        r["is_rec_ma"] = (r["key"] == ma_key)
        r["is_rec_invvol"] = (r["key"] == invvol_key)
        r["is_rec_rp"] = (r["key"] == rp_key)

    return {
        "rows": rows,
        # 단순 모멘텀
        "momentum_rec_name": mom_name,
        "momentum_rec_key": mom_key,
        "momentum_rec_desc": mom_desc,
        # VAA
        "vaa_rec_name": vaa_name,
        "vaa_rec_key": vaa_key,
        "vaa_rec_desc": vaa_desc,
        # MA200
        "ma_rec_name": ma_name,
        "ma_rec_key": ma_key,
        "ma_rec_desc": ma_desc,
        # 역변동성
        "invvol_rec_desc": invvol_desc,
        "invvol_rec_key": invvol_key,
        # Risk Parity
        "rp_rec_desc": rp_desc,
        "rp_rec_key":  rp_key,
        "error": "",
    }
