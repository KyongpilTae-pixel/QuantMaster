# -*- coding: utf-8 -*-
"""포지션 관리 · 매도 신호.

매도 규칙 (백테스트 검증):
  1. 추세이탈 매도: 종가가 100일 이동평균선을 하회 → 최대낙폭 -19%→-15% 감소
  2. 손절가 가드:   추천가 대비 -15% 하회 → 파국적 손실 방지 백스톱
  둘 중 하나라도 닿으면 '매도 신호'. 아니면 '보유 유지'.

포지션 원장(positions.json)에 추천가·추천일을 저장하고 매 실행마다 상태를 갱신한다.
"""
import json
import os

import numpy as np
import pandas as pd

LEDGER   = "positions.json"
MA_DAYS  = 100
STOP_PCT = 0.15


def load_ledger():
    if os.path.exists(LEDGER):
        return json.load(open(LEDGER, encoding="utf-8"))
    return {}


def save_ledger(led):
    json.dump(led, open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def open_positions(led, tickers, prices, asof):
    """신규 추천 종목을 원장에 편입 (이미 있으면 유지)."""
    for tk in tickers:
        if tk not in led and tk in prices.columns:
            led[tk] = {
                "entry_date": str(asof),
                "entry": float(prices[tk].dropna().iloc[-1]),
            }
    return led


def evaluate(led, prices):
    """보유 종목별 상태·손절가·매도신호 계산. 매도신호 종목은 원장에서 제외."""
    ma     = prices.rolling(MA_DAYS).mean()
    rows   = []
    closed = []

    for tk, info in list(led.items()):
        if tk not in prices.columns:
            continue
        s = prices[tk].dropna()
        if len(s) < 2:
            continue

        cur   = float(s.iloc[-1])
        entry = info["entry"]
        ret   = (cur / entry - 1) * 100

        ma100 = float(ma[tk].dropna().iloc[-1]) if ma[tk].notna().any() else np.nan
        stop_price  = entry * (1 - STOP_PCT)
        trend_break = (not np.isnan(ma100)) and cur < ma100
        stop_break  = cur < stop_price
        signal      = trend_break or stop_break
        reason      = (
            "추세이탈(100일선 하회)" if trend_break
            else ("손절가 도달" if stop_break else "-")
        )

        rows.append(dict(
            ticker=tk,
            entry=round(entry, 2),
            cur=round(cur, 2),
            ret=round(ret, 1),
            ma100=round(ma100, 2) if not np.isnan(ma100) else None,
            stop=round(stop_price, 2),
            signal=signal,
            reason=reason,
            entry_date=info["entry_date"],
        ))
        if signal:
            closed.append(tk)

    for tk in closed:
        led.pop(tk, None)

    rows.sort(key=lambda r: (not r["signal"], -r["ret"]))
    return rows, closed


def manage(prices, new_tickers, asof):
    """포지션 원장을 업데이트하고 현재 상태 rows와 매도 완료 목록을 반환."""
    led = load_ledger()
    rows, closed = evaluate(led, prices)          # 기존 보유 평가(매도신호 산출)
    led = open_positions(led, new_tickers, prices, asof)  # 이번 추천 신규 편입
    save_ledger(led)
    return rows, closed
