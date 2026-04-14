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
            created_at    TEXT NOT NULL,
            scan_mode     TEXT NOT NULL DEFAULT 'quant'
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
        CREATE TABLE IF NOT EXISTS whale_results (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id         INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
            name           TEXT,
            symbol         TEXT,
            market         TEXT,
            signal_date    TEXT,
            score          INTEGER,
            signal_type    TEXT,
            obv_spike      INTEGER,
            breakout       INTEGER DEFAULT 0,
            alpha          INTEGER,
            short_cover    INTEGER,
            close          REAL,
            volume_ratio   REAL,
            applied_step   TEXT
        );
    """)
    conn.commit()
    # 기존 DB 마이그레이션
    for sql in [
        "ALTER TABLE scan_runs ADD COLUMN scan_mode TEXT NOT NULL DEFAULT 'quant'",
        "ALTER TABLE whale_results ADD COLUMN breakout INTEGER DEFAULT 0",
    ]:
        try:
            conn.execute(sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # 이미 존재하면 무시


def save_scan(
    market: str,
    vwap_period: int,
    target_pbr: float,
    min_cap_label: str,
    results: list,
    scan_mode: str = "quant",
) -> int:
    """퀀트 스캔 결과를 DB에 저장하고 생성된 run_id를 반환."""
    conn = _connect()
    _ensure_tables(conn)
    now = datetime.now()
    cur = conn.execute(
        "INSERT INTO scan_runs (scan_date, market, vwap_period, target_pbr, min_cap_label, created_at, scan_mode) "
        "VALUES (?,?,?,?,?,?,?)",
        (now.strftime("%Y-%m-%d"), market, vwap_period, target_pbr,
         min_cap_label, now.isoformat(timespec="seconds"), scan_mode),
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


def save_whale_scan(
    market: str,
    results: list,
) -> int:
    """세력 탐지 스캔 결과를 DB에 저장하고 생성된 run_id를 반환."""
    conn = _connect()
    _ensure_tables(conn)
    now = datetime.now()
    cur = conn.execute(
        "INSERT INTO scan_runs (scan_date, market, vwap_period, target_pbr, min_cap_label, created_at, scan_mode) "
        "VALUES (?,?,?,?,?,?,?)",
        (now.strftime("%Y-%m-%d"), market, 0, 0.0, "-", now.isoformat(timespec="seconds"), "whale"),
    )
    run_id = cur.lastrowid
    conn.executemany(
        """INSERT INTO whale_results
           (run_id, name, symbol, market, signal_date, score, signal_type,
            obv_spike, breakout, alpha, short_cover, close, volume_ratio, applied_step)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (run_id, r.name, r.symbol, r.market, r.signal_date, r.score,
             r.signal_type, int(r.obv_spike), int(r.breakout), int(r.alpha),
             int(r.short_cover), r.close, r.volume_ratio, r.applied_step)
            for r in results
        ],
    )
    conn.commit()
    conn.close()
    return run_id


def get_run_mode(run_id: int) -> str:
    """run_id의 scan_mode를 반환 ('quant' | 'whale')."""
    conn = _connect()
    _ensure_tables(conn)
    row = conn.execute(
        "SELECT scan_mode FROM scan_runs WHERE id = ?", (run_id,)
    ).fetchone()
    conn.close()
    return row["scan_mode"] if row else "quant"


def load_run_list() -> list[dict]:
    """저장된 스캔 실행 목록을 최신순으로 반환."""
    conn = _connect()
    _ensure_tables(conn)
    rows = conn.execute(
        """SELECT s.id, s.scan_date, s.market, s.vwap_period, s.target_pbr,
                  s.min_cap_label, s.created_at, s.scan_mode,
                  COUNT(r.id) AS quant_count,
                  COUNT(w.id) AS whale_count
           FROM scan_runs s
           LEFT JOIN scan_results r ON r.run_id = s.id
           LEFT JOIN whale_results w ON w.run_id = s.id
           GROUP BY s.id
           ORDER BY s.id DESC"""
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        mode = r["scan_mode"] or "quant"
        count = r["whale_count"] if mode == "whale" else r["quant_count"]
        if mode == "whale":
            label = (
                f"[세력탐지]  {r['scan_date']}  {r['market']}  [{count}종목]"
            )
        else:
            label = (
                f"[퀀트]  {r['scan_date']}  {r['market']}  "
                f"VWAP{r['vwap_period']}  PBR≤{r['target_pbr']}  [{count}종목]"
            )
        result.append({"id": str(r["id"]), "label": label, "scan_mode": mode})
    return result


def load_scan_results(run_id: int) -> list[dict]:
    """특정 run_id의 퀀트 스캔 결과를 반환."""
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


def load_whale_results(run_id: int) -> list[dict]:
    """특정 run_id의 세력 탐지 결과를 반환."""
    conn = _connect()
    _ensure_tables(conn)
    rows = conn.execute(
        "SELECT * FROM whale_results WHERE run_id = ? ORDER BY score DESC",
        (run_id,),
    ).fetchall()
    conn.close()
    return [
        {
            "name": r["name"] or "",
            "symbol": r["symbol"] or "",
            "market": r["market"] or "KOSPI",
            "signal_date": r["signal_date"] or "",
            "score": r["score"] or 0,
            "signal_type": r["signal_type"] or "-",
            "obv_spike": bool(r["obv_spike"]),
            "breakout": bool(r["breakout"]),
            "alpha": bool(r["alpha"]),
            "short_cover": bool(r["short_cover"]),
            "close": r["close"] or 0.0,
            "volume_ratio": r["volume_ratio"] or 0.0,
            "applied_step": r["applied_step"] or "원본",
        }
        for r in rows
    ]
