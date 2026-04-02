"""SQLite 기반 스캔 결과 저장/로드 모듈."""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "quant_history.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scan_runs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date     TEXT NOT NULL,
            market        TEXT NOT NULL,
            vwap_period   INTEGER NOT NULL,
            target_pbr    REAL NOT NULL,
            min_cap_label TEXT NOT NULL,
            created_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scan_results (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id         INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
            name           TEXT,
            symbol         TEXT,
            market_raw     TEXT,
            pbr            REAL,
            psr            REAL,
            div_yield      TEXT,
            mfi            REAL,
            obv_ok         INTEGER,
            vwap_price     REAL,
            close          REAL,
            vwap_gap       REAL,
            condition      TEXT,
            applied_pbr    REAL,
            applied_gpa    REAL,
            applied_mfi    INTEGER,
            applied_obv    INTEGER,
            applied_min_cap TEXT,
            currency       TEXT,
            market_cap_str TEXT
        );
    """)
    conn.commit()


def save_scan(
    market: str,
    vwap_period: int,
    target_pbr: float,
    min_cap_label: str,
    results: list,
) -> int:
    """스캔 결과를 DB에 저장하고 생성된 run_id를 반환."""
    conn = _connect()
    _ensure_tables(conn)
    now = datetime.now()
    cur = conn.execute(
        "INSERT INTO scan_runs (scan_date, market, vwap_period, target_pbr, min_cap_label, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (now.strftime("%Y-%m-%d"), market, vwap_period, target_pbr,
         min_cap_label, now.isoformat(timespec="seconds")),
    )
    run_id = cur.lastrowid
    conn.executemany(
        """INSERT INTO scan_results
           (run_id, name, symbol, market_raw, pbr, psr, div_yield, mfi, obv_ok,
            vwap_price, close, vwap_gap, condition, applied_pbr, applied_gpa,
            applied_mfi, applied_obv, applied_min_cap, currency, market_cap_str)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (run_id, r.name, r.symbol, r.market_raw, r.pbr, r.psr, r.div_yield,
             r.mfi, int(r.obv_ok), r.vwap_price, r.close, r.vwap_gap, r.condition,
             r.applied_pbr, r.applied_gpa, r.applied_mfi, int(r.applied_obv),
             r.applied_min_cap, r.currency, r.market_cap_str)
            for r in results
        ],
    )
    conn.commit()
    conn.close()
    return run_id


def load_run_list() -> list[dict]:
    """저장된 스캔 실행 목록을 최신순으로 반환."""
    conn = _connect()
    _ensure_tables(conn)
    rows = conn.execute(
        """SELECT s.id, s.scan_date, s.market, s.vwap_period, s.target_pbr,
                  s.min_cap_label, s.created_at,
                  COUNT(r.id) AS result_count
           FROM scan_runs s
           LEFT JOIN scan_results r ON r.run_id = s.id
           GROUP BY s.id
           ORDER BY s.id DESC"""
    ).fetchall()
    conn.close()
    return [
        {
            "id": str(r["id"]),
            "label": (
                f"{r['scan_date']}  {r['market']}  "
                f"VWAP{r['vwap_period']}  PBR≤{r['target_pbr']}  "
                f"[{r['result_count']}종목]"
            ),
        }
        for r in rows
    ]


def load_scan_results(run_id: int) -> list[dict]:
    """특정 run_id의 스캔 결과를 반환."""
    conn = _connect()
    _ensure_tables(conn)
    rows = conn.execute(
        "SELECT * FROM scan_results WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    conn.close()
    return [
        {
            "name": r["name"] or "",
            "symbol": r["symbol"] or "",
            "market_raw": r["market_raw"] or "KOSPI",
            "pbr": r["pbr"] or 0.0,
            "psr": r["psr"] or 0.0,
            "div_yield": r["div_yield"] or "-",
            "mfi": r["mfi"] or 0.0,
            "obv_ok": bool(r["obv_ok"]),
            "vwap_price": r["vwap_price"] or 0.0,
            "close": r["close"] or 0.0,
            "vwap_gap": r["vwap_gap"] or 0.0,
            "condition": r["condition"] or "",
            "applied_pbr": r["applied_pbr"] or 1.2,
            "applied_gpa": r["applied_gpa"] or 0.6,
            "applied_mfi": r["applied_mfi"] or 50,
            "applied_obv": bool(r["applied_obv"]),
            "applied_min_cap": r["applied_min_cap"] or "전체",
            "currency": r["currency"] or "KRW",
            "market_cap_str": r["market_cap_str"] or "-",
        }
        for r in rows
    ]
