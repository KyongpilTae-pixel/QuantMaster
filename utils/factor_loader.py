"""
다중 팩터 로더 — Piotroski F-Score (Phase 1) + EV/EBITDA · P/FCF (Phase 2)

Phase 1: Piotroski F-Score — 9점 만점 재무 건전성 점수.
  수익성(4) + 레버리지·유동성(3) + 영업 효율성(2)
Phase 2: 가치 팩터 — EV/EBITDA, P/FCF (현금흐름 기반 저평가 측정)
"""

import yfinance as yf


def _yf_symbol(symbol: str, market: str) -> str:
    if market in ("KOSPI", "KOSDAQ"):
        return symbol + (".KS" if market == "KOSPI" else ".KQ")
    return symbol


def _get(df, keys: list[str], col: int = 0):
    """df(재무제표)에서 keys 중 첫 번째로 존재하는 행의 col 번째 열 값 반환."""
    for k in keys:
        if k in df.index:
            vals = df.loc[k].dropna()
            if len(vals) > col:
                v = vals.iloc[col]
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
    return None


def load_f_score(symbol: str, market: str = "KOSPI") -> dict:
    """
    Piotroski F-Score 계산 (9점 만점).

    Returns:
        {
          "score": int (0-9),
          "criteria": [{"name": str, "group": str, "passed": bool, "na": bool, "value": str}],
          "error": str | None
        }
    """
    yf_sym = _yf_symbol(symbol, market)
    is_us  = market not in ("KOSPI", "KOSDAQ")

    try:
        ticker = yf.Ticker(yf_sym)
        fin = ticker.financials      # income statement (연간, columns=날짜 최신→과거)
        cf  = ticker.cashflow        # cash flow (연간)
        bs  = ticker.balance_sheet   # balance sheet (연간)

        if fin is None or fin.empty:
            return {"score": 0, "criteria": [], "error": "재무 데이터를 불러올 수 없습니다. (ETF이거나 데이터 미제공 종목)"}

        # ── 핵심 수치 추출 (t=최근, t1=전년) ─────────────────────────────
        net_income_t   = _get(fin, ["Net Income"])
        net_income_t1  = _get(fin, ["Net Income"], col=1)

        revenue_t      = _get(fin, ["Total Revenue", "Revenue", "Revenues"])
        revenue_t1     = _get(fin, ["Total Revenue", "Revenue", "Revenues"], col=1)

        gross_t        = _get(fin, ["Gross Profit"])
        gross_t1       = _get(fin, ["Gross Profit"], col=1)

        ocf_t          = _get(cf,  ["Operating Cash Flow",
                                    "Cash From Operating Activities",
                                    "Total Cash From Operating Activities",
                                    "Net Cash From Operating Activities"])

        total_assets_t  = _get(bs, ["Total Assets"])
        total_assets_t1 = _get(bs, ["Total Assets"], col=1)

        lt_debt_t       = _get(bs, ["Long Term Debt", "Long-Term Debt",
                                    "Long Term Debt And Capital Lease Obligation"])
        lt_debt_t1      = _get(bs, ["Long Term Debt", "Long-Term Debt",
                                    "Long Term Debt And Capital Lease Obligation"], col=1)

        curr_assets_t   = _get(bs, ["Current Assets", "Total Current Assets"])
        curr_assets_t1  = _get(bs, ["Current Assets", "Total Current Assets"], col=1)

        curr_liab_t     = _get(bs, ["Current Liabilities", "Total Current Liabilities"])
        curr_liab_t1    = _get(bs, ["Current Liabilities", "Total Current Liabilities"], col=1)

        shares_t        = _get(bs, ["Common Stock", "Ordinary Shares Number",
                                    "Share Issued", "Common Stock Equity"])
        shares_t1       = _get(bs, ["Common Stock", "Ordinary Shares Number",
                                    "Share Issued", "Common Stock Equity"], col=1)

        # ── 점수 계산 ───────────────────────────────────────────────────
        criteria = []
        score = 0

        def _c(name: str, group: str, passed, value_str: str):
            nonlocal score
            is_na = passed is None
            ok    = bool(passed) if not is_na else False
            if ok:
                score += 1
            criteria.append({
                "name":   name,
                "group":  group,
                "passed": ok,
                "na":     is_na,
                "value":  value_str,
            })

        def _fmt_amount(v):
            if v is None:
                return "?"
            if is_us:
                return f"${v/1e9:.1f}B" if abs(v) >= 1e9 else f"${v/1e6:.0f}M"
            return f"{v/1e8:.0f}억"

        # ── 수익성 (Profitability) ───────────────────────────────────────
        if net_income_t is not None and total_assets_t is not None and total_assets_t > 0:
            roa_t = net_income_t / total_assets_t
            _c("ROA > 0 (총자산수익률)", "수익성", roa_t > 0, f"{roa_t*100:.2f}%")
        else:
            _c("ROA > 0 (총자산수익률)", "수익성", None, "데이터 없음")

        if ocf_t is not None:
            _c("영업현금흐름 > 0", "수익성", ocf_t > 0, _fmt_amount(ocf_t))
        else:
            _c("영업현금흐름 > 0", "수익성", None, "데이터 없음")

        if (net_income_t is not None and net_income_t1 is not None
                and total_assets_t is not None and total_assets_t1 is not None
                and total_assets_t > 0 and total_assets_t1 > 0):
            roa_t  = net_income_t  / total_assets_t
            roa_t1 = net_income_t1 / total_assets_t1
            delta  = roa_t - roa_t1
            _c("ROA 전년 대비 개선", "수익성", delta > 0, f"Δ{delta*100:+.2f}%pt")
        else:
            _c("ROA 전년 대비 개선", "수익성", None, "데이터 없음")

        if (ocf_t is not None and net_income_t is not None
                and total_assets_t is not None and total_assets_t > 0):
            accrual = ocf_t         / total_assets_t
            roa_now = net_income_t  / total_assets_t
            _c("발생주의 (OCF/자산 > ROA)", "수익성", accrual > roa_now,
               f"OCF률={accrual*100:.2f}% ROA={roa_now*100:.2f}%")
        else:
            _c("발생주의 (OCF/자산 > ROA)", "수익성", None, "데이터 없음")

        # ── 레버리지·유동성 ─────────────────────────────────────────────
        if (lt_debt_t is not None and lt_debt_t1 is not None
                and total_assets_t is not None and total_assets_t1 is not None
                and total_assets_t > 0 and total_assets_t1 > 0):
            lev_t  = lt_debt_t  / total_assets_t
            lev_t1 = lt_debt_t1 / total_assets_t1
            _c("장기부채 비율 감소", "레버리지·유동성", lev_t < lev_t1,
               f"{lev_t*100:.1f}% → {lev_t1*100:.1f}%")
        elif lt_debt_t is not None and lt_debt_t1 is not None:
            _c("장기부채 비율 감소", "레버리지·유동성", lt_debt_t < lt_debt_t1,
               "감소" if lt_debt_t < lt_debt_t1 else "증가")
        else:
            _c("장기부채 비율 감소", "레버리지·유동성", None, "데이터 없음")

        if (curr_assets_t is not None and curr_liab_t is not None and curr_liab_t > 0
                and curr_assets_t1 is not None and curr_liab_t1 is not None and curr_liab_t1 > 0):
            cr_t  = curr_assets_t  / curr_liab_t
            cr_t1 = curr_assets_t1 / curr_liab_t1
            _c("유동비율 증가", "레버리지·유동성", cr_t > cr_t1,
               f"{cr_t:.2f}x → {cr_t1:.2f}x")
        else:
            _c("유동비율 증가", "레버리지·유동성", None, "데이터 없음")

        if shares_t is not None and shares_t1 is not None and shares_t1 > 0:
            diluted = shares_t > shares_t1 * 1.02   # 2% 이상 증가 시 희석 판정
            _c("신주 발행 없음", "레버리지·유동성", not diluted,
               "희석 없음" if not diluted else f"+{(shares_t/shares_t1-1)*100:.1f}% 증가")
        else:
            _c("신주 발행 없음", "레버리지·유동성", None, "데이터 없음")

        # ── 영업 효율성 ─────────────────────────────────────────────────
        if (gross_t is not None and gross_t1 is not None
                and revenue_t is not None and revenue_t1 is not None
                and revenue_t > 0 and revenue_t1 > 0):
            gm_t  = gross_t  / revenue_t
            gm_t1 = gross_t1 / revenue_t1
            _c("매출총이익률 증가", "영업 효율성", gm_t > gm_t1,
               f"{gm_t*100:.1f}% → {gm_t1*100:.1f}%")
        else:
            _c("매출총이익률 증가", "영업 효율성", None, "데이터 없음")

        if (revenue_t is not None and revenue_t1 is not None
                and total_assets_t is not None and total_assets_t1 is not None
                and total_assets_t > 0 and total_assets_t1 > 0):
            at_t  = revenue_t  / total_assets_t
            at_t1 = revenue_t1 / total_assets_t1
            _c("자산회전율 증가", "영업 효율성", at_t > at_t1,
               f"{at_t:.3f}x → {at_t1:.3f}x")
        else:
            _c("자산회전율 증가", "영업 효율성", None, "데이터 없음")

        return {"score": score, "criteria": criteria, "error": None}

    except Exception as e:
        return {"score": 0, "criteria": [], "error": f"계산 오류: {str(e)[:100]}"}


def load_value_metrics(symbol: str, market: str = "KOSPI") -> dict:
    """
    EV/EBITDA, P/FCF 계산 (Phase 2).

    Returns:
        {
          "ev_ebitda": float | None,
          "p_fcf":     float | None,
          "ev":        float | None,   # 억원 or $M
          "ebitda":    float | None,
          "fcf":       float | None,
          "mktcap":    float | None,
          "currency":  str,
          "error":     str | None
        }
    """
    is_us  = market not in ("KOSPI", "KOSDAQ")
    yf_sym = _yf_symbol(symbol, market)
    cur    = "USD" if is_us else "KRW"

    try:
        ticker = yf.Ticker(yf_sym)
        info   = ticker.info or {}
        fin    = ticker.financials
        cf     = ticker.cashflow
        bs     = ticker.balance_sheet

        # ── 시가총액 ────────────────────────────────────────────────────────
        mktcap = (info.get("marketCap")
                  or info.get("market_cap"))

        # ── EBITDA ──────────────────────────────────────────────────────────
        # yfinance info에서 먼저 시도 (이미 계산된 값)
        ebitda = info.get("ebitda")
        if ebitda is None and fin is not None and not fin.empty:
            ebit  = _get(fin, ["EBIT", "Operating Income"])
            da    = _get(fin, ["Reconciled Depreciation",
                                "Depreciation And Amortization",
                                "Depreciation Amortization Depletion"])
            if ebit is not None and da is not None:
                ebitda = ebit + da

        # ── FCF (Free Cash Flow) ─────────────────────────────────────────────
        # FCF = OCF - CapEx
        fcf = info.get("freeCashflow")
        if fcf is None and cf is not None and not cf.empty:
            ocf   = _get(cf, ["Operating Cash Flow",
                               "Cash From Operating Activities",
                               "Total Cash From Operating Activities"])
            capex = _get(cf, ["Capital Expenditure",
                               "Purchase Of PPE",
                               "Capital Expenditures"])
            if ocf is not None and capex is not None:
                fcf = ocf + capex   # capex는 음수로 보고되는 경우가 많음
                if fcf > ocf:       # capex가 양수로 보고된 경우
                    fcf = ocf - capex

        # ── 부채·현금 (EV 계산용) ────────────────────────────────────────────
        total_debt = info.get("totalDebt")
        cash       = info.get("totalCash") or info.get("cash")

        if total_debt is None and bs is not None and not bs.empty:
            lt  = _get(bs, ["Long Term Debt", "Long-Term Debt"])
            st  = _get(bs, ["Current Debt", "Short Term Debt",
                             "Current Portion Of Long Term Debt"])
            total_debt = (lt or 0) + (st or 0)

        if cash is None and bs is not None and not bs.empty:
            cash = _get(bs, ["Cash And Cash Equivalents",
                              "Cash Cash Equivalents And Short Term Investments"])

        # ── EV = 시가총액 + 부채 - 현금 ────────────────────────────────────
        ev = None
        if mktcap is not None:
            ev = mktcap + (total_debt or 0) - (cash or 0)

        # ── 멀티플 계산 ─────────────────────────────────────────────────────
        ev_ebitda = None
        if ev is not None and ebitda and ebitda > 0:
            ev_ebitda = round(ev / ebitda, 1)

        p_fcf = None
        if mktcap is not None and fcf and fcf > 0:
            p_fcf = round(mktcap / fcf, 1)

        # ── 표시용 단위 변환 ─────────────────────────────────────────────────
        def _fmt(v):
            if v is None:
                return None
            if is_us:
                return round(v / 1e9, 2)   # $B
            return round(v / 1e8, 0)       # 억원

        return {
            "ev_ebitda": ev_ebitda,
            "p_fcf":     p_fcf,
            "ev":        _fmt(ev),
            "ebitda":    _fmt(ebitda),
            "fcf":       _fmt(fcf),
            "mktcap":    _fmt(mktcap),
            "currency":  cur,
            "error":     None,
        }

    except Exception as e:
        return {
            "ev_ebitda": None, "p_fcf": None, "ev": None,
            "ebitda": None, "fcf": None, "mktcap": None,
            "currency": cur, "error": f"계산 오류: {str(e)[:100]}",
        }
