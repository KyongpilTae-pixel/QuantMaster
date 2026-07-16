"""
스캔 성과 추적 모듈.

퀀트/눌림목/세력 스캔 결과에서 발굴된 종목을 DB에 저장하고,
매일 현재가를 업데이트해 발굴 이후 수익률을 추적한다.

테이블:
  tracked_picks  — 발굴 종목 원본 (스캔날짜 · 지표값)
  tracked_prices — 날짜별 가격 업데이트 (30거래일까지)
"""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "quant_history.db"

_TRACK_DAYS = 30  # 최대 추적 거래일 수

_SCAN_MODE_LABELS = {
    "quant":    "퀀트",
    "pullback": "눌림목",
    "whale":    "세력",
}


# ---------------------------------------------------------------------------
# DB 초기화
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 3000")
    return conn


def _ensure_tracker_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tracked_picks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date     TEXT NOT NULL,
            scan_mode     TEXT NOT NULL,
            market        TEXT NOT NULL,
            code          TEXT NOT NULL,
            name          TEXT,
            close_at_pick REAL,
            ret_1w        REAL,
            ret_3m        REAL,
            rsi14         REAL,
            vwap          REAL,
            mfi           REAL,
            pbr           REAL,
            created_at    TEXT NOT NULL,
            UNIQUE(scan_date, scan_mode, market, code)
        );
        CREATE TABLE IF NOT EXISTS tracked_prices (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            pick_id       INTEGER NOT NULL REFERENCES tracked_picks(id) ON DELETE CASCADE,
            update_date   TEXT NOT NULL,
            close         REAL,
            ret_pct       REAL,
            days_elapsed  INTEGER,
            UNIQUE(pick_id, update_date)
        );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# 발굴 종목 저장
# ---------------------------------------------------------------------------

def save_scan_picks(scan_mode: str, market: str, results: list[dict]) -> int:
    """스캔 결과에서 종목을 tracked_picks 에 저장.

    이미 오늘 같은 (scan_mode, market, code) 조합이 있으면 무시(IGNORE).
    반환: 새로 삽입된 건수.
    """
    if not results:
        return 0

    today  = datetime.today().strftime("%Y-%m-%d")
    now    = datetime.now().isoformat(timespec="seconds")
    conn   = _connect()
    _ensure_tracker_tables(conn)

    inserted = 0
    for r in results:
        code  = r.get("code") or r.get("symbol", "")
        name  = r.get("name", "")
        close = r.get("close") or r.get("close_price")
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO tracked_picks
                   (scan_date, scan_mode, market, code, name,
                    close_at_pick, ret_1w, ret_3m, rsi14, vwap, mfi, pbr, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    today, scan_mode, market, code, name,
                    float(close) if close else None,
                    r.get("ret_1w"),
                    r.get("ret_3m"),
                    r.get("rsi14") or r.get("rsi"),
                    r.get("vwap_price") or r.get("vwap"),
                    r.get("mfi"),
                    r.get("pbr"),
                    now,
                ),
            )
            inserted += cur.rowcount
        except Exception:
            pass

    conn.commit()
    conn.close()
    return inserted


# ---------------------------------------------------------------------------
# 현재가 업데이트
# ---------------------------------------------------------------------------

def _fetch_price(args: tuple) -> tuple:
    """(code, is_us) → (code, current_close | None)"""
    code, is_us = args
    try:
        import FinanceDataReader as fdr
        end   = datetime.today()
        start = end - timedelta(days=7)
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Close"] > 0].dropna(subset=["Close"])
        if df.empty:
            return code, None
        return code, float(df["Close"].iloc[-1])
    except Exception:
        return code, None


def _trading_days_between(date_str: str) -> int:
    """scan_date 에서 오늘까지 거래일 수 (주말 제외 근사값)."""
    try:
        import numpy as np
        start = datetime.strptime(date_str, "%Y-%m-%d").date()
        end   = datetime.today().date()
        if end <= start:
            return 0
        return int(np.busday_count(start, end))
    except Exception:
        try:
            # numpy 없을 때 캘린더일 × 5/7 근사
            cal = (datetime.today().date() - datetime.strptime(date_str, "%Y-%m-%d").date()).days
            return max(0, int(cal * 5 / 7))
        except Exception:
            return 0


def update_pick_prices() -> int:
    """오늘 가격이 없는 활성(≤30거래일) 종목의 현재가를 일괄 업데이트.

    반환: 업데이트된 건수.
    """
    conn   = _connect()
    _ensure_tracker_tables(conn)
    today  = datetime.today().strftime("%Y-%m-%d")
    cutoff = (datetime.today() - timedelta(days=_TRACK_DAYS + 15)).strftime("%Y-%m-%d")

    # 업데이트가 필요한 종목 조회 (오늘 가격 없고, 30일 이내)
    rows = conn.execute(
        """SELECT p.id, p.code, p.market, p.close_at_pick, p.scan_date
           FROM tracked_picks p
           WHERE p.scan_date >= ?
             AND NOT EXISTS (
               SELECT 1 FROM tracked_prices t
               WHERE t.pick_id = p.id AND t.update_date = ?
             )""",
        (cutoff, today),
    ).fetchall()
    conn.close()

    if not rows:
        return 0

    # 종목별 현재가 병렬 조회
    unique_codes = {r["code"]: r["market"] not in ("KOSPI", "KOSDAQ") for r in rows}
    with ThreadPoolExecutor(max_workers=10) as ex:
        price_map = dict(ex.map(_fetch_price, [(c, is_us) for c, is_us in unique_codes.items()]))

    # DB 업데이트
    conn    = _connect()
    updated = 0
    for r in rows:
        cur_price = price_map.get(r["code"])
        if cur_price is None:
            continue
        close_at_pick = r["close_at_pick"] or 0
        ret_pct = ((cur_price - close_at_pick) / close_at_pick * 100
                   if close_at_pick else None)
        days = _trading_days_between(r["scan_date"])
        try:
            conn.execute(
                """INSERT OR REPLACE INTO tracked_prices
                   (pick_id, update_date, close, ret_pct, days_elapsed)
                   VALUES (?,?,?,?,?)""",
                (r["id"], today, cur_price, ret_pct, days),
            )
            updated += 1
        except Exception:
            pass

    conn.commit()
    conn.close()
    return updated


# ---------------------------------------------------------------------------
# 성과 조회
# ---------------------------------------------------------------------------

def load_tracked_picks(
    days: int = 30,
    scan_mode: str | None = None,
    market: str | None = None,
) -> list[dict]:
    """발굴 종목 + 최신 수익률 목록 반환.

    Args:
        days: 최근 N거래일 이내 발굴 종목만
        scan_mode: None이면 전체, 'quant'/'pullback'/'whale'
        market: None이면 전체
    """
    cutoff = (datetime.today() - timedelta(days=days + 15)).strftime("%Y-%m-%d")
    conn   = _connect()
    _ensure_tracker_tables(conn)

    # 각 종목의 최신 가격 서브쿼리
    sql = """
        SELECT p.*,
               t.close      AS cur_close,
               t.ret_pct    AS cur_ret_pct,
               t.days_elapsed,
               t.update_date
        FROM tracked_picks p
        LEFT JOIN tracked_prices t ON t.id = (
            SELECT id FROM tracked_prices
            WHERE pick_id = p.id
            ORDER BY update_date DESC LIMIT 1
        )
        WHERE p.scan_date >= ?
    """
    params: list = [cutoff]

    if scan_mode:
        sql += " AND p.scan_mode = ?"
        params.append(scan_mode)
    if market:
        sql += " AND p.market = ?"
        params.append(market)

    sql += " ORDER BY p.scan_date DESC, p.id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    result = []
    for r in rows:
        days_el  = r["days_elapsed"] or _trading_days_between(r["scan_date"])
        ret_pct  = r["cur_ret_pct"]
        is_us    = r["market"] not in ("KOSPI", "KOSDAQ")
        close_at = r["close_at_pick"] or 0
        cur_cl   = r["cur_close"]

        close_str = (f"{close_at:,.2f}" if is_us else f"{close_at:,.0f}") if close_at else "-"
        cur_str   = (f"{cur_cl:,.2f}" if is_us else f"{cur_cl:,.0f}") if cur_cl else "-"
        ret_str   = f"{ret_pct:+.2f}%" if ret_pct is not None else "추적중"

        result.append({
            "pick_id":        r["id"],
            "scan_date":      r["scan_date"],
            "scan_mode":      r["scan_mode"],
            "scan_mode_label":_SCAN_MODE_LABELS.get(r["scan_mode"], r["scan_mode"]),
            "market":         r["market"],
            "code":           r["code"],
            "name":           r["name"] or "",
            "close_at_pick":  close_at,
            "close_at_str":   close_str,
            "cur_close":      cur_cl,
            "cur_close_str":  cur_str,
            "ret_pct":        ret_pct,
            "ret_str":        ret_str,
            "days_elapsed":   days_el,
            "update_date":    r["update_date"] or "",
            # bool flags
            "ret_positive":   (ret_pct or 0) > 0,
            "ret_known":      ret_pct is not None,
            "is_us":          is_us,
        })

    return result


def get_tracker_summary(picks: list[dict]) -> dict:
    """성과 요약 dict (UI 카드용)."""
    known  = [p for p in picks if p["ret_known"]]
    pos    = [p for p in known if p["ret_positive"]]
    avg    = sum(p["ret_pct"] for p in known) / len(known) if known else None
    best   = max(known, key=lambda p: p["ret_pct"]) if known else None
    worst  = min(known, key=lambda p: p["ret_pct"]) if known else None

    return {
        "total":        len(picks),
        "tracked":      len(known),
        "positive":     len(pos),
        "win_rate":     round(len(pos) / len(known) * 100, 1) if known else None,
        "avg_ret":      round(avg, 2) if avg is not None else None,
        "best_name":    best["name"] if best else "-",
        "best_ret":     best["ret_pct"] if best else None,
        "worst_name":   worst["name"] if worst else "-",
        "worst_ret":    worst["ret_pct"] if worst else None,
        # str
        "win_rate_str": f"{len(pos) / len(known) * 100:.1f}%" if known else "-",
        "avg_ret_str":  f"{avg:+.2f}%" if avg is not None else "-",
        "best_str":     f"{best['name']} ({best['ret_pct']:+.2f}%)" if best else "-",
        "worst_str":    f"{worst['name']} ({worst['ret_pct']:+.2f}%)" if worst else "-",
        # bool
        "avg_positive": (avg or 0) >= 0,
    }
