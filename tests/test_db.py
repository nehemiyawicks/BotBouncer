import sys
import time
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import db

TEST_DB = Path("test_botbouncer.db")


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield


def test_init_creates_tables():
    with db._conn() as con:
        tables = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert {"flagged_comments", "flagged_users", "enrolled_subs", "account_cache"} <= tables


def test_enroll_and_remove_sub():
    db.enroll_sub("testSub")
    subs = db.get_enrolled_subs()
    assert any(s["subreddit"] == "testSub" for s in subs)

    db.remove_sub("testSub")
    subs = db.get_enrolled_subs()
    assert not any(s["subreddit"] == "testSub" for s in subs)


def test_enroll_with_threshold():
    db.enroll_sub("threshSub", threshold=25)
    subs = db.get_enrolled_subs()
    row = next(s for s in subs if s["subreddit"] == "threshSub")
    assert row["threshold_override"] == 25


def test_whitelist_user():
    db.enroll_sub("whitelistSub")
    result = db.whitelist_user("whitelistSub", "testuser")
    assert result is True

    subs = db.get_enrolled_subs()
    row = next(s for s in subs if s["subreddit"] == "whitelistSub")
    whitelist = json.loads(row["whitelisted_users"])
    assert "testuser" in whitelist


def test_log_flagged_comment_increments_count():
    db.enroll_sub("flagSub")
    count = db.log_flagged_comment("abc123", "flagSub", "testuser", 25, ["signal1"], "flag")
    assert count == 1

    count = db.log_flagged_comment("def456", "flagSub", "testuser", 30, ["signal2"], "flag")
    assert count == 2


def test_escalation_at_three_flags():
    db.enroll_sub("escalateSub")
    for i in range(3):
        db.log_flagged_comment(f"id{i}", "escalateSub", "repeatuser", 25, [], "flag")

    count = db.get_flag_count("repeatuser")
    assert count == 3

    db.mark_escalated("repeatuser")
    with db._conn() as con:
        row = con.execute(
            "SELECT escalated FROM flagged_users WHERE username = 'repeatuser'"
        ).fetchone()
    assert row["escalated"] == 1


def test_dismiss_comment():
    db.enroll_sub("dismissSub")
    db.log_flagged_comment("dismissme", "dismissSub", "user1", 22, [], "flag")
    db.dismiss_comment("dismissme")

    with db._conn() as con:
        row = con.execute(
            "SELECT dismissed FROM flagged_comments WHERE comment_id = 'dismissme'"
        ).fetchone()
    assert row["dismissed"] == 1


def test_account_cache_hit():
    db.cache_account("cacheduser", 100, 5000, ["comment1", "comment2"])
    result = db.get_cached_account("cacheduser", ttl_hours=24)
    assert result is not None
    assert result["age_days"] == 100
    assert result["karma"] == 5000
    assert result["comment_history"] == ["comment1", "comment2"]


def test_account_cache_miss_expired(monkeypatch):
    db.cache_account("expireduser", 50, 200, [])
    # Simulate expired by patching time
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + 25 * 3600)
    result = db.get_cached_account("expireduser", ttl_hours=24)
    assert result is None


def test_account_cache_miss_nonexistent():
    result = db.get_cached_account("nobody", ttl_hours=24)
    assert result is None


def test_get_user_flags_filters_dismissed():
    db.enroll_sub("filterSub")
    db.log_flagged_comment("keep1", "filterSub", "filteruser", 25, [], "flag")
    db.log_flagged_comment("dismiss1", "filterSub", "filteruser", 25, [], "flag")
    db.dismiss_comment("dismiss1")

    flags = db.get_user_flags("filteruser")
    assert len(flags) == 1
    assert flags[0]["comment_id"] == "keep1"


def test_set_threshold():
    db.enroll_sub("threshSub2")
    db.set_threshold("threshSub2", 30)
    subs = db.get_enrolled_subs()
    row = next(s for s in subs if s["subreddit"] == "threshSub2")
    assert row["threshold_override"] == 30
