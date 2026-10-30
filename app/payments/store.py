"""Alerts and what analysts decided about them, in SQLite. Confirmed and rejected alerts are the labels for the next training."""
from __future__ import annotations

import json
import sqlite3
import threading

from app import config

STATUSES = ["new", "confirmed_fraud", "false_alarm"]

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    role TEXT NOT NULL,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (role, username)
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id TEXT,
    ts REAL NOT NULL,
    payer TEXT NOT NULL,
    payee TEXT NOT NULL,
    amount REAL NOT NULL,
    score INTEGER NOT NULL,
    level TEXT NOT NULL,
    action TEXT NOT NULL,
    likely TEXT,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS alerts_payee ON alerts(payee);
"""


def init() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
        # Payment numbers start again when the simulation restarts, so they are not unique over time. Analysts' decisions are
        # the labels for the next training and must survive; alerts nobody looked at belong to the old run.
        _conn.execute("DELETE FROM alerts WHERE status = 'new'")
        _conn.commit()


def clear() -> None:
    with _lock:
        _conn.execute("DELETE FROM alerts")
        _conn.commit()


def save_alert(alert: dict) -> int:
    with _lock:
        cur = _conn.execute(
            "INSERT INTO alerts (txn_id, ts, payer, payee, amount, score, level, action, likely, source, status, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (alert["txn_id"], alert["ts"], alert["payer"], alert["payee"], alert["amount"], alert["score"], alert["level"], alert["action"],
             alert.get("likely"), alert["source"], alert.get("status", "new"), json.dumps(alert, ensure_ascii=False)))
        _conn.commit()
        return int(cur.lastrowid)


def _row(row: sqlite3.Row) -> dict:
    alert = json.loads(row["payload"])
    alert["id"] = row["id"]
    alert["status"] = row["status"]
    return alert


def get_alert(alert_id: int) -> dict | None:
    with _lock:
        row = _conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    return _row(row) if row else None


def list_alerts(status: str | None = None, limit: int = 50, payee: str | None = None) -> list[dict]:
    where, args = [], []
    if status:
        where.append("status = ?")
        args.append(status)
    if payee:
        where.append("payee = ?")
        args.append(payee)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with _lock:
        rows = _conn.execute(f"SELECT * FROM alerts {clause} ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
    return [_row(r) for r in rows]


def set_status(alert_id: int, status: str) -> dict | None:
    with _lock:
        cur = _conn.execute("UPDATE alerts SET status = ? WHERE id = ?", (status, alert_id))
        _conn.commit()
        if not cur.rowcount:
            return None
    return get_alert(alert_id)


def labelled_counts() -> dict:
    with _lock:
        rows = _conn.execute("SELECT status, COUNT(*) AS n FROM alerts GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


def add_account(role: str, username: str, password_hash: str, name: str) -> bool:
    """False when the username is taken."""
    with _lock:
        cur = _conn.execute("INSERT OR IGNORE INTO accounts (role, username, password_hash, name) VALUES (?, ?, ?, ?)", (role, username, password_hash, name))
        _conn.commit()
        return cur.rowcount == 1


def get_account(role: str, username: str) -> dict | None:
    with _lock:
        row = _conn.execute("SELECT * FROM accounts WHERE role = ? AND username = ?", (role, username)).fetchone()
    return dict(row) if row else None
