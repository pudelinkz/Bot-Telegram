import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

DB_PATH = Path(__file__).with_name("antispam.sqlite3")

DEFAULTS = {
    "anti_link": True,
    "banned_words": ["free money", "scam link"],
    "allowed_domains": ["t.me"],
    "flood_max_messages": 6,
    "flood_window_seconds": 8,
    "duplicate_limit": 3,
    "warnings_before_mute": 2,
    "warnings_before_ban": 4,
    "mute_minutes": 10,
}

def connect():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            username TEXT, reason TEXT NOT NULL, message_text TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS warnings (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(chat_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS blocked_users (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            username TEXT, display_name TEXT, created_at TEXT NOT NULL,
            PRIMARY KEY(chat_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS tracked_messages (
            chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(chat_id, message_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tracked_user
          ON tracked_messages(chat_id, user_id, created_at);
        """)
        for key, value in DEFAULTS.items():
            con.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                (key, json.dumps(value))
            )

def get_settings():
    with connect() as con:
        rows = con.execute("SELECT key,value FROM settings").fetchall()
    result = dict(DEFAULTS)
    for row in rows:
        try: result[row["key"]] = json.loads(row["value"])
        except (ValueError, TypeError): pass
    return result

def save_settings(values):
    with connect() as con:
        for key, value in values.items():
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value))
            )

def add_violation(chat_id, user_id, username, reason, message_text=""):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as con:
        con.execute(
            "INSERT INTO violations(chat_id,user_id,username,reason,message_text,created_at) VALUES(?,?,?,?,?,?)",
            (chat_id, user_id, username, reason, (message_text or "")[:500], stamp)
        )

def increment_warning(chat_id, user_id):
    with connect() as con:
        con.execute(
            "INSERT INTO warnings(chat_id,user_id,count) VALUES(?,?,1) "
            "ON CONFLICT(chat_id,user_id) DO UPDATE SET count=count+1",
            (chat_id, user_id)
        )
        row = con.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        return row["count"] if row else 1

def get_warning_count(chat_id, user_id):
    with connect() as con:
        row = con.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        return row["count"] if row else 0

def clear_warnings(chat_id, user_id):
    with connect() as con:
        con.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))

def stats():
    with connect() as con:
        total = con.execute("SELECT COUNT(*) n FROM violations").fetchone()["n"]
        today = con.execute("SELECT COUNT(*) n FROM violations WHERE substr(created_at,1,10)=?",
                            (datetime.now(timezone.utc).date().isoformat(),)).fetchone()["n"]
        reasons = con.execute("SELECT reason, COUNT(*) n FROM violations GROUP BY reason ORDER BY n DESC LIMIT 8").fetchall()
        recent = con.execute("SELECT chat_id,user_id,username,reason,created_at FROM violations ORDER BY id DESC LIMIT 20").fetchall()
    return {"total": total, "today": today, "reasons": [dict(r) for r in reasons], "recent": [dict(r) for r in recent]}

def block_user(chat_id, user_id, username=None, display_name=None):
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as con:
        con.execute(
            "INSERT INTO blocked_users(chat_id,user_id,username,display_name,created_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(chat_id,user_id) DO UPDATE SET username=excluded.username, display_name=excluded.display_name",
            (chat_id, user_id, username, display_name, stamp)
        )

def unblock_user(chat_id, user_id):
    with connect() as con:
        cur = con.execute("DELETE FROM blocked_users WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        return cur.rowcount > 0

def is_blocked_user(chat_id, user_id):
    with connect() as con:
        row = con.execute("SELECT 1 FROM blocked_users WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        return row is not None

def list_blocked_users(chat_id):
    with connect() as con:
        rows = con.execute(
            "SELECT user_id,username,display_name,created_at FROM blocked_users WHERE chat_id=? ORDER BY created_at DESC",
            (chat_id,)
        ).fetchall()
    return [dict(row) for row in rows]

def track_message(chat_id, user_id, message_id):
    """Keep message IDs seen since this feature was deployed; only retain the last 48 hours."""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=47)).isoformat(timespec="seconds")
    stamp = now.isoformat(timespec="seconds")
    with connect() as con:
        con.execute(
            "INSERT OR IGNORE INTO tracked_messages(chat_id,user_id,message_id,created_at) VALUES(?,?,?,?)",
            (chat_id, user_id, message_id, stamp)
        )
        con.execute("DELETE FROM tracked_messages WHERE created_at < ?", (cutoff,))
        # Bound database growth for very active groups.
        con.execute("""
            DELETE FROM tracked_messages WHERE rowid IN (
                SELECT rowid FROM tracked_messages WHERE chat_id=?
                ORDER BY created_at DESC LIMIT -1 OFFSET 5000
            )
        """, (chat_id,))

def get_tracked_message_ids(chat_id, user_id, limit=100):
    with connect() as con:
        rows = con.execute(
            "SELECT message_id FROM tracked_messages WHERE chat_id=? AND user_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (chat_id, user_id, limit)
        ).fetchall()
    return [row["message_id"] for row in rows]

def forget_tracked_message(chat_id, message_id):
    with connect() as con:
        con.execute("DELETE FROM tracked_messages WHERE chat_id=? AND message_id=?", (chat_id, message_id))

def clear_tracked_messages(chat_id, user_id):
    with connect() as con:
        con.execute("DELETE FROM tracked_messages WHERE chat_id=? AND user_id=?", (chat_id, user_id))
