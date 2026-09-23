"""cloud-015 Task B — US GP touch/reclaim 진입 시점 재무 버킷 분석
look-ahead 방지: 진입일 기준 직전 회계연도 재무만 사용
"""
import sys, io, json, warnings, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import yfinance as yf

# us_eventstudy_results_v3.json 로드
with open(r"C:\project\quant\us_eventstudy_results_v3.json", encoding="utf-8") as f:
    v3 = json.load(f)

trades = v3["trades"]
tickers = list(set(t["ticker"] for t in trades))
print(f"총 {len(trades)}건 거래, {len(tickers)}종목 → yfinance fundamentals 수집")

# ── yfinance 펀더멘털 수집 ─────────────────────────────────────────────────
# 각 종목: sector, annual financials(4년), balance_sheet
fundamentals = {}
failed = []

for i, tk in enumerate(tickers):
    try:
        ticker = yf.Ticker(tk)
        info   = ticker.info

        sector = info.get("sector", "Unknown")
        # 연간 재무제표 (컬럼 = 회계연도 종료일, 최근 4년)
        fin = ticker.financials  # rows: metrics, cols: fiscal year dates
        bs  = ticker.balance_sheet

        # Total Revenue 연도별
        rev_row   = fin.loc["Total Revenue"]  if "Total Revenue"   in fin.index else None
        oi_row    = fin.loc["Operating Income"] if "Operating Income" in fin.index else None
        debt_row  = bs.loc["Total Debt"]       if "Total Debt"       in bs.index  else None
        equity_row= bs.loc["Stockholders Equity"] if "Stockholders Equity" in bs.index else None

        # 날짜 정렬 (최신 → 오래된 순)
        def sorted_series(row):
            if row is None:
                return None
            s = row.dropna().sort_index(ascending=False)
            return s

        fundamentals[tk] = {
            "sector":  sector,
            "revenue": sorted_series(rev_row),
            "op_income": sorted_series(oi_row),
            "debt": sorted_series(debt_row),
            "equity": sorted_series(equity_row),
        }
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(tickers)} 완료", flush=True)
        time.sleep(0.3)
    except Exception as e:
        failed.append(tk)
        fundamentals[tk] = {"sector": "Unknown", "revenue": None, "op_income": None,
                             "debt": None, "equity": None}

print(f"수집 완료. 실패: {failed}")


# ── 진입 시점 직전 회계연도 재무 추출 (look-ahead 방지) ──────────────────────
def get_prior_fiscal(series, entry_date, lag_months=4):
    """
    entry_date 기준 lag_months(기본4개월) 이전까지 공시됐을 회계연도만 선택.
    보수적: 회계연도 종료 후 4개월이 지나야 공시됐다고 가정.
    """
    if series is None or len(series) == 0:
        return None
    cutoff = pd.Timestamp(entry_date) - pd.DateOffset(months=lag_months)
    # 회계연도 종료일이 cutoff 이전인 것 중 가장 최근
    available = series[series.index <= cutoff]
    if len(available) == 0:
        return None
    return float(available.iloc[0])


def classify_trade(trade):
    tk   = trade["ticker"]
    date = trade["date"]
    ret  = trade["ret12m"]
    stop = trade["stop_hit"]
    mdd  = trade["mdd"]

    fdata = fundamentals.get(tk, {})

    # 섹터
    sector = fdata.get("sector", "Unknown")

    # 매출 YoY (진입 시점 직전 연도 vs 그 전년도)
    rev_s = fdata.get("revenue")
    rev_yoy = None
    if rev_s is not None and len(rev_s) >= 2:
        r0 = get_prior_fiscal(rev_s, date)
        # 한 해 이전
        cutoff = pd.Timestamp(date) - pd.DateOffset(months=4)
        older  = rev_s[rev_s.index <= cutoff]
        r1 = float(older.iloc[1]) if len(older) >= 2 else None
        if r0 and r1 and r1 != 0:
            rev_yoy = (r0 - r1) / abs(r1) * 100

    # 영업이익 (흑자/적자)
    oi = get_prior_fiscal(fdata.get("op_income"), date)
    profitable = None if oi is None else (oi > 0)

    # 부채비율 D/E
    debt   = get_prior_fiscal(fdata.get("debt"), date)
    equity = get_prior_fiscal(fdata.get("equity"), date)
    de_ratio = None
    if debt is not None and equity is not None and equity > 0:
        de_ratio = debt / equity

    # 버킷 라벨
    # 매출성장: YoY > 10% → 성장, < 0% → 역성장, else 보합
    rev_bucket = "data_missing"
    if rev_yoy is not None:
        if rev_yoy > 10:
            rev_bucket = "rev_growth"
        elif rev_yoy < 0:
            rev_bucket = "rev_decline"
        else:
            rev_bucket = "rev_flat"

    # 영업이익
    profit_bucket = "data_missing"
    if profitable is not None:
        profit_bucket = "profitable" if profitable else "unprofitable"

    # 부채비율: D/E < 0.5 저부채, 0.5-2 보통, > 2 고부채
    debt_bucket = "data_missing"
    if de_ratio is not None:
        if de_ratio < 0.5:
            debt_bucket = "low_debt"
        elif de_ratio <= 2.0:
            debt_bucket = "mid_debt"
        else:
            debt_bucket = "high_debt"

    return {
        "ticker":       tk,
        "date":         date,
        "type":         trade["type"],
        "ret12m":       ret,
        "stop_hit":     stop,
        "mdd":          mdd,
        "sector":       sector,
        "rev_yoy":      round(rev_yoy, 1) if rev_yoy is not None else None,
        "profitable":   profitable,
        "de_ratio":     round(de_ratio, 2) if de_ratio is not None else None,
        "rev_bucket":   rev_bucket,
        "profit_bucket": profit_bucket,
        "debt_bucket":  debt_bucket,
        "collapse":     ret <= -10.0,  # -10% 손절 = 붕괴형
    }


enriched = [classify_trade(t) for t in trades]
print(f"\n분류 완료: {len(enriched)}건")

# ── 버킷별 집계 ─────────────────────────────────────────────────────────────
def bucket_stats(rows, key):
    buckets = {}
    for r in rows:
        b = r[key]
        if b not in buckets:
            buckets[b] = []
        buckets[b].append(r)

    result = {}
    for b, rs in buckets.items():
        rets     = [r["ret12m"] for r in rs]
        collapse = [r["collapse"] for r in rs]
        result[b] = {
            "n":          len(rs),
            "win_rate":   round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1),
            "avg_ret":    round(np.mean(rets), 2),
            "stop_rate":  round(sum(collapse) / len(collapse) * 100, 1),
            "avg_mdd":    round(np.mean([r["mdd"] for r in rs]), 1),
        }
    return result

print("\n[섹터별]")
sector_stats = bucket_stats(enriched, "sector")
for b, s in sorted(sector_stats.items(), key=lambda x: x[1]["stop_rate"]):
    if s["n"] >= 3:
        print(f"  {b:<30} n={s['n']:>3} 승률={s['win_rate']:>5.1f}% 평균={s['avg_ret']:>+7.2f}% 붕괴율={s['stop_rate']:>5.1f}%")

print("\n[매출 성장 버킷별]")
rev_stats = bucket_stats(enriched, "rev_bucket")
for b, s in rev_stats.items():
    print(f"  {b:<15} n={s['n']:>3} 승률={s['win_rate']:>5.1f}% 평균={s['avg_ret']:>+7.2f}% 붕괴율={s['stop_rate']:>5.1f}%")

print("\n[흑자/적자 버킷별]")
profit_stats = bucket_stats(enriched, "profit_bucket")
for b, s in profit_stats.items():
    print(f"  {b:<15} n={s['n']:>3} 승률={s['win_rate']:>5.1f}% 평균={s['avg_ret']:>+7.2f}% 붕괴율={s['stop_rate']:>5.1f}%")

print("\n[부채비율 버킷별]")
debt_stats = bucket_stats(enriched, "debt_bucket")
for b, s in debt_stats.items():
    print(f"  {b:<15} n={s['n']:>3} 승률={s['win_rate']:>5.1f}% 평균={s['avg_ret']:>+7.2f}% 붕괴율={s['stop_rate']:>5.1f}%")

# 복합 필터: 저부채 + 흑자 + 매출성장
quality = [r for r in enriched if r["profit_bucket"] == "profitable"
           and r["debt_bucket"] == "low_debt" and r["rev_bucket"] == "rev_growth"]
rest    = [r for r in enriched if r not in quality]

def simple_stats(rows, label):
    if not rows:
        print(f"  {label}: 표본 없음")
        return
    rets = [r["ret12m"] for r in rows]
    stop = sum(r["collapse"] for r in rows)
    print(f"  {label}: n={len(rows)} 승률={round(sum(1 for r in rets if r>0)/len(rets)*100,1)}% "
          f"평균={round(np.mean(rets),2):+.2f}% 붕괴율={round(stop/len(rows)*100,1)}%")

print("\n[복합 품질 필터 — 저부채+흑자+매출성장 vs 나머지]")
simple_stats(quality, "품질OK  ")
simple_stats(rest,    "나머지  ")
print(f"  품질OK 표본 비율: {len(quality)}/{len(enriched)} = {round(len(quality)/len(enriched)*100,1)}%")

# 저장
out = {
    "total_trades": len(enriched),
    "quality_filter": {"n": len(quality), "ratio_pct": round(len(quality)/len(enriched)*100,1)},
    "bucket_stats": {
        "sector": sector_stats,
        "revenue": rev_stats,
        "profitability": profit_stats,
        "debt": debt_stats,
    },
    "trades_enriched": enriched,
}
out_json = r"C:\project\quant\quality_filter_results_B.json"
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"\n저장: {out_json}")
print("완료")
