"""Alerts and what analysts decided about them, in SQLite. Confirmed and rejected alerts are the labels for the next training."""
from __future__ import annotations

import json
import sqlite3
import threading
import time

from app import config

STATUSES = ["new", "confirmed_fraud", "false_alarm"]

_lock = threading.Lock()
_conn = None

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

COMMUNITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id {serial},
    created REAL NOT NULL,
    username TEXT NOT NULL,
    role TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    amount REAL,
    note TEXT NOT NULL DEFAULT '',
    score INTEGER NOT NULL,
    level TEXT NOT NULL,
    action TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS checks_user ON checks(username, role);
CREATE TABLE IF NOT EXISTS reports (
    payee TEXT NOT NULL,
    reporter TEXT NOT NULL,
    created REAL NOT NULL,
    PRIMARY KEY (payee, reporter)
);
CREATE TABLE IF NOT EXISTS blocks (
    payee TEXT PRIMARY KEY,
    blocked_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS feed_posts (
    id {serial},
    created REAL NOT NULL,
    author TEXT NOT NULL,
    author_name TEXT NOT NULL,
    payee TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    body TEXT NOT NULL,
    hidden INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS feed_votes (
    post_id BIGINT NOT NULL,
    voter TEXT NOT NULL,
    value INTEGER NOT NULL,
    PRIMARY KEY (post_id, voter)
);
CREATE TABLE IF NOT EXISTS feed_comments (
    id {serial},
    post_id BIGINT NOT NULL,
    created REAL NOT NULL,
    author TEXT NOT NULL,
    author_name TEXT NOT NULL,
    body TEXT NOT NULL,
    hidden INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS feed_comments_post ON feed_comments(post_id);
"""


class _Postgres:
    """Gives Postgres the small part of the sqlite3 interface this file uses. Used when a database address is set, as on Vercel."""

    def __init__(self, url: str):
        self.url = url
        self._connect()

    def _connect(self) -> None:
        import psycopg
        from psycopg.rows import dict_row
        self.conn = psycopg.connect(self.url, autocommit=True, row_factory=dict_row, connect_timeout=10)

    def execute(self, sql: str, args=()):
        import psycopg
        sql = sql.replace("?", "%s")
        try:
            return self.conn.execute(sql, args)
        except psycopg.OperationalError:     # free databases sleep and drop idle connections
            self._connect()
            return self.conn.execute(sql, args)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        self.conn.close()


def is_shared() -> bool:
    return bool(config.DATABASE_URL)


def init() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        if is_shared():
            _conn = _Postgres(config.DATABASE_URL)
            _conn.executescript(SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY") + COMMUNITY_SCHEMA.format(serial="BIGSERIAL PRIMARY KEY"))
            return     # many short-lived copies share this database, so one starting up must not clear anything
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA + COMMUNITY_SCHEMA.format(serial="INTEGER PRIMARY KEY AUTOINCREMENT"))
        # Payment numbers start again when the simulation restarts, so they are not unique over time. Analysts' decisions are
        # the labels for the next training and must survive; alerts nobody looked at belong to the old run.
        _conn.execute("DELETE FROM alerts WHERE status = 'new'")
        _conn.commit()


def _insert(sql: str, args: tuple) -> int:
    """Runs an INSERT and returns the new row's id, on either database."""
    cur = _conn.execute(sql + (" RETURNING id" if is_shared() else ""), args)
    _conn.commit()
    return int(cur.fetchone()["id"]) if is_shared() else int(cur.lastrowid)


def clear() -> None:
    with _lock:
        _conn.execute("DELETE FROM alerts")
        _conn.commit()


def clear_community() -> None:
    """For tests."""
    with _lock:
        for table in ("checks", "reports", "blocks", "feed_posts", "feed_votes", "feed_comments"):
            _conn.execute(f"DELETE FROM {table}")
        _conn.commit()


def save_alert(alert: dict) -> int:
    with _lock:
        if is_shared():     # a free database is small, and alerts nobody labelled are only useful for a while
            _conn.execute("DELETE FROM alerts WHERE status = 'new' AND id < (SELECT COALESCE(MAX(id), 0) - 5000 FROM alerts)")
        return _insert(
            "INSERT INTO alerts (txn_id, ts, payer, payee, amount, score, level, action, likely, source, status, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (alert["txn_id"], alert["ts"], alert["payer"], alert["payee"], alert["amount"], alert["score"], alert["level"], alert["action"],
             alert.get("likely"), alert["source"], alert.get("status", "new"), json.dumps(alert, ensure_ascii=False)))


def _row(row) -> dict:
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
        cur = _conn.execute("INSERT INTO accounts (role, username, password_hash, name) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING", (role, username, password_hash, name))
        _conn.commit()
        return cur.rowcount == 1


def get_account(role: str, username: str) -> dict | None:
    with _lock:
        row = _conn.execute("SELECT * FROM accounts WHERE role = ? AND username = ?", (role, username)).fetchone()
    return dict(row) if row else None


# --- what a person has checked ---------------------------------------------------------

def add_check(username: str, role: str, kind: str, subject: str, amount: float | None, note: str, score: int, level: str, action: str, summary: str) -> int:
    with _lock:
        return _insert("INSERT INTO checks (created, username, role, kind, subject, amount, note, score, level, action, summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (time.time(), username, role, kind, subject[:300], amount, note[:300], score, level, action, summary[:300]))


def list_checks(username: str | None, role: str | None, q: str = "", action: str = "", limit: int = 100) -> list[dict]:
    """One person's checks, or everyone's when username is None."""
    where, args = [], []
    if username is not None:
        where += ["username = ?", "role = ?"]
        args += [username, role]
    if q:
        where.append("(LOWER(subject) LIKE ? OR LOWER(note) LIKE ?)")
        args += [f"%{q.lower()}%"] * 2
    if action:
        where.append("action = ?")
        args.append(action)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    with _lock:
        rows = _conn.execute(f"SELECT * FROM checks {clause} ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
    return [dict(r) for r in rows]


def clear_checks(username: str, role: str) -> None:
    with _lock:
        _conn.execute("DELETE FROM checks WHERE username = ? AND role = ?", (username, role))
        _conn.commit()


# --- reports and blocks ------------------------------------------------------------------

def add_report(payee: str, reporter: str) -> bool:
    """True the first time this account reports this UPI ID. One account counts once, however often it reports."""
    with _lock:
        cur = _conn.execute("INSERT INTO reports (payee, reporter, created) VALUES (?, ?, ?) ON CONFLICT DO NOTHING", (payee, reporter, time.time()))
        _conn.commit()
        return cur.rowcount == 1


def report_count(payee: str) -> int:
    with _lock:
        row = _conn.execute("SELECT COUNT(*) AS n FROM reports WHERE payee = ?", (payee,)).fetchone()
    return int(row["n"])


def most_reported(limit: int = 50) -> list[dict]:
    with _lock:
        rows = _conn.execute("SELECT payee, COUNT(*) AS n FROM reports GROUP BY payee ORDER BY n DESC, payee LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def set_block(payee: str, by: str, reason: str) -> None:
    with _lock:
        _conn.execute("INSERT INTO blocks (payee, blocked_by, reason, created) VALUES (?, ?, ?, ?) ON CONFLICT (payee) DO UPDATE SET blocked_by = excluded.blocked_by, reason = excluded.reason, created = excluded.created",
                      (payee, by, reason[:300], time.time()))
        _conn.commit()


def remove_block(payee: str) -> bool:
    with _lock:
        cur = _conn.execute("DELETE FROM blocks WHERE payee = ?", (payee,))
        _conn.commit()
        return cur.rowcount > 0


def get_block(payee: str) -> dict | None:
    with _lock:
        row = _conn.execute("SELECT * FROM blocks WHERE payee = ?", (payee,)).fetchone()
    return dict(row) if row else None


def list_blocks() -> list[dict]:
    with _lock:
        rows = _conn.execute("SELECT * FROM blocks ORDER BY created DESC").fetchall()
    return [dict(r) for r in rows]


# --- the scam feed ---------------------------------------------------------------------

def add_post(author: str, author_name: str, payee: str, category: str, body: str) -> int:
    with _lock:
        return _insert("INSERT INTO feed_posts (created, author, author_name, payee, category, body) VALUES (?, ?, ?, ?, ?, ?)",
                       (time.time(), author, author_name, payee, category, body))


def list_posts(sort: str = "new", limit: int = 30, offset: int = 0, include_hidden: bool = False) -> list[dict]:
    order = "votes DESC, p.id DESC" if sort == "top" else "p.id DESC"
    where = "" if include_hidden else "WHERE p.hidden = 0"
    sql = (f"SELECT p.*, COALESCE((SELECT SUM(v.value) FROM feed_votes v WHERE v.post_id = p.id), 0) AS votes, "
           f"(SELECT COUNT(*) FROM feed_comments c WHERE c.post_id = p.id AND c.hidden = 0) AS comments "
           f"FROM feed_posts p {where} ORDER BY {order} LIMIT ? OFFSET ?")
    with _lock:
        rows = _conn.execute(sql, (limit, offset)).fetchall()
    return [dict(r) for r in rows]


def get_post(post_id: int) -> dict | None:
    with _lock:
        row = _conn.execute("SELECT p.*, COALESCE((SELECT SUM(v.value) FROM feed_votes v WHERE v.post_id = p.id), 0) AS votes, "
                            "(SELECT COUNT(*) FROM feed_comments c WHERE c.post_id = p.id AND c.hidden = 0) AS comments FROM feed_posts p WHERE p.id = ?", (post_id,)).fetchone()
    return dict(row) if row else None


def hide_post(post_id: int) -> bool:
    with _lock:
        cur = _conn.execute("UPDATE feed_posts SET hidden = 1 WHERE id = ?", (post_id,))
        _conn.commit()
        return cur.rowcount > 0


def vote(post_id: int, voter: str, value: int) -> None:
    with _lock:
        if value == 0:
            _conn.execute("DELETE FROM feed_votes WHERE post_id = ? AND voter = ?", (post_id, voter))
        else:
            _conn.execute("INSERT INTO feed_votes (post_id, voter, value) VALUES (?, ?, ?) ON CONFLICT (post_id, voter) DO UPDATE SET value = excluded.value", (post_id, voter, value))
        _conn.commit()


def my_votes(voter: str) -> dict[int, int]:
    with _lock:
        rows = _conn.execute("SELECT post_id, value FROM feed_votes WHERE voter = ?", (voter,)).fetchall()
    return {int(r["post_id"]): int(r["value"]) for r in rows}


def add_comment(post_id: int, author: str, author_name: str, body: str) -> int:
    with _lock:
        return _insert("INSERT INTO feed_comments (post_id, created, author, author_name, body) VALUES (?, ?, ?, ?, ?)", (post_id, time.time(), author, author_name, body))


def list_comments(post_id: int) -> list[dict]:
    with _lock:
        rows = _conn.execute("SELECT * FROM feed_comments WHERE post_id = ? AND hidden = 0 ORDER BY id", (post_id,)).fetchall()
    return [dict(r) for r in rows]
