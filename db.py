import sqlite3
import json
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path("botbouncer.db")


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS flagged_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                comment_id TEXT UNIQUE,
                subreddit TEXT,
                username TEXT,
                score INTEGER,
                signals TEXT,
                verdict TEXT,
                timestamp REAL,
                dismissed INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS flagged_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                flag_count INTEGER DEFAULT 0,
                last_flagged REAL,
                escalated INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS enrolled_subs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subreddit TEXT UNIQUE,
                threshold_override INTEGER,
                custom_phrases TEXT,
                whitelisted_users TEXT,
                enrolled_at REAL
            );

            CREATE TABLE IF NOT EXISTS account_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                age_days INTEGER,
                karma INTEGER,
                comment_history_json TEXT,
                cached_at REAL
            );
        """)


def log_flagged_comment(comment_id, subreddit, username, score, signals, verdict):
    with _conn() as con:
        con.execute(
            """INSERT OR IGNORE INTO flagged_comments
               (comment_id, subreddit, username, score, signals, verdict, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (comment_id, subreddit, username, score, json.dumps(signals), verdict, time.time()),
        )
        cur = con.execute(
            "SELECT flag_count FROM flagged_users WHERE username = ?", (username,)
        )
        row = cur.fetchone()
        if row:
            con.execute(
                "UPDATE flagged_users SET flag_count = flag_count + 1, last_flagged = ? WHERE username = ?",
                (time.time(), username),
            )
        else:
            con.execute(
                "INSERT INTO flagged_users (username, flag_count, last_flagged) VALUES (?, 1, ?)",
                (username, time.time()),
            )
        cur2 = con.execute("SELECT flag_count FROM flagged_users WHERE username = ?", (username,))
        return cur2.fetchone()["flag_count"]


def dismiss_comment(comment_id):
    with _conn() as con:
        con.execute("UPDATE flagged_comments SET dismissed = 1 WHERE comment_id = ?", (comment_id,))


def get_flag_count(username):
    with _conn() as con:
        cur = con.execute("SELECT flag_count FROM flagged_users WHERE username = ?", (username,))
        row = cur.fetchone()
        return row["flag_count"] if row else 0


def mark_escalated(username):
    with _conn() as con:
        con.execute("UPDATE flagged_users SET escalated = 1 WHERE username = ?", (username,))


def get_user_flags(username):
    with _conn() as con:
        cur = con.execute(
            "SELECT * FROM flagged_comments WHERE username = ? AND dismissed = 0 ORDER BY timestamp DESC",
            (username,),
        )
        return [dict(r) for r in cur.fetchall()]


def enroll_sub(subreddit, threshold=None):
    with _conn() as con:
        con.execute(
            """INSERT OR IGNORE INTO enrolled_subs (subreddit, enrolled_at)
               VALUES (?, ?)""",
            (subreddit, time.time()),
        )
        if threshold is not None:
            con.execute(
                "UPDATE enrolled_subs SET threshold_override = ? WHERE subreddit = ?",
                (threshold, subreddit),
            )


def remove_sub(subreddit):
    with _conn() as con:
        con.execute("DELETE FROM enrolled_subs WHERE subreddit = ?", (subreddit,))


def get_enrolled_subs():
    with _conn() as con:
        cur = con.execute("SELECT * FROM enrolled_subs")
        return [dict(r) for r in cur.fetchall()]


def whitelist_user(subreddit, username):
    with _conn() as con:
        cur = con.execute(
            "SELECT whitelisted_users FROM enrolled_subs WHERE subreddit = ?", (subreddit,)
        )
        row = cur.fetchone()
        if not row:
            return False
        existing = json.loads(row["whitelisted_users"] or "[]")
        if username not in existing:
            existing.append(username)
        con.execute(
            "UPDATE enrolled_subs SET whitelisted_users = ? WHERE subreddit = ?",
            (json.dumps(existing), subreddit),
        )
        return True


def set_threshold(subreddit, threshold):
    with _conn() as con:
        con.execute(
            "UPDATE enrolled_subs SET threshold_override = ? WHERE subreddit = ?",
            (threshold, subreddit),
        )


def get_cached_account(username, ttl_hours=24):
    with _conn() as con:
        cur = con.execute(
            "SELECT * FROM account_cache WHERE username = ?", (username,)
        )
        row = cur.fetchone()
        if not row:
            return None
        age = time.time() - row["cached_at"]
        if age > ttl_hours * 3600:
            return None
        return {
            "age_days": row["age_days"],
            "karma": row["karma"],
            "comment_history": json.loads(row["comment_history_json"] or "[]"),
        }


def cache_account(username, age_days, karma, comment_history):
    with _conn() as con:
        con.execute(
            """INSERT OR REPLACE INTO account_cache
               (username, age_days, karma, comment_history_json, cached_at)
               VALUES (?, ?, ?, ?, ?)""",
            (username, age_days, karma, json.dumps(comment_history), time.time()),
        )
