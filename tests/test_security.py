"""
Security tests: verify credentials never appear in logs, error messages, or outputs.
"""

import io
import logging
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


FAKE_CREDS = {
    "REDDIT_CLIENT_ID": "fake_client_id_12345",
    "REDDIT_CLIENT_SECRET": "fake_secret_abc999",
    "REDDIT_USERNAME": "fake_bot_user",
    "REDDIT_PASSWORD": "super_secret_password_xyz",
    "MONITOR_SUBS": "testsub",
    "REDDIT_USER_AGENT": "BotBouncer/1.0",
}


def _capture_logs(module_name: str):
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    logger = logging.getLogger(module_name)
    logger.addHandler(handler)
    return buf, handler, logger


def _assert_no_creds_in_text(text: str):
    for key, val in FAKE_CREDS.items():
        if key in ("MONITOR_SUBS", "REDDIT_USER_AGENT"):
            continue  # not sensitive
        assert val not in text, (
            f"Credential value for {key} found in output: ...{text[:200]}..."
        )


def test_poll_missing_secret_exits_cleanly(monkeypatch):
    """Missing secret should exit with a clear message, not a Python traceback with env dump."""
    for key in FAKE_CREDS:
        monkeypatch.delenv(key, raising=False)

    import poll
    buf, handler, logger = _capture_logs("poll")
    try:
        with pytest.raises(SystemExit):
            poll.make_reddit()
    finally:
        logger.removeHandler(handler)

    output = buf.getvalue()
    # Should name the missing variable but never print a secret value
    _assert_no_creds_in_text(output)
    assert "REDDIT_CLIENT_ID" in output or output == ""  # either named or silent


def test_bot_missing_secret_exits_cleanly(monkeypatch):
    for key in FAKE_CREDS:
        monkeypatch.delenv(key, raising=False)

    import bot
    buf, handler, logger = _capture_logs("botbouncer")
    try:
        with pytest.raises(SystemExit):
            bot.make_reddit()
    finally:
        logger.removeHandler(handler)

    _assert_no_creds_in_text(buf.getvalue())


def test_no_credentials_in_scorer_output():
    """Scorer never touches credentials -- verify ScorerResult contains no env data."""
    from scorer import CommentScorer

    with patch.dict(os.environ, FAKE_CREDS):
        scorer = CommentScorer()
        result = scorer.score(
            "Certainly! It is important to note that this is a nuanced issue.",
            account_age_days=5,
            karma=10,
            comment_history=["word " * 210] * 5,
        )

    result_str = str(result.signals_triggered) + result.verdict
    _assert_no_creds_in_text(result_str)


def test_db_operations_contain_no_credentials(tmp_path, monkeypatch):
    """DB records should contain comment/score data only, never env var values."""
    import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sec_test.db")
    db.init_db()
    db.enroll_sub("testsub")

    with patch.dict(os.environ, FAKE_CREDS):
        db.log_flagged_comment(
            "cid1", "testsub", "someuser", 25,
            ["structural:bullet points"], "flag"
        )

    with db._conn() as con:
        rows = con.execute("SELECT * FROM flagged_comments").fetchall()
        for row in rows:
            row_text = " ".join(str(v) for v in dict(row).values())
            _assert_no_creds_in_text(row_text)


def test_poll_api_error_does_not_log_credentials(monkeypatch, tmp_path):
    """If PRAW raises an exception, the log message must not include credential values."""
    import poll

    monkeypatch.chdir(tmp_path)
    (tmp_path / "seen_comments.txt").write_text("")

    with patch.dict(os.environ, FAKE_CREDS):
        mock_reddit = MagicMock()
        mock_reddit.subreddit.side_effect = Exception(
            f"Connection failed (not a real error)"
        )

        buf, handler, logger = _capture_logs("poll")
        try:
            with patch("poll.make_reddit", return_value=mock_reddit), \
                 patch("poll.get_enrolled_subs", return_value=[{"subreddit": "testsub", "threshold": 20, "whitelisted_users": []}]):
                poll.run()
        finally:
            logger.removeHandler(handler)

        _assert_no_creds_in_text(buf.getvalue())


def test_gitignore_covers_sensitive_files():
    """Verify .gitignore includes all files that must never be committed."""
    gitignore = Path(".gitignore").read_text()
    must_ignore = [".env", "seen_comments.txt", "*.db", "bot.log"]
    for pattern in must_ignore:
        assert pattern in gitignore, f".gitignore is missing: {pattern}"


def test_env_example_has_no_real_values():
    """
    .env.example must not contain real-looking secrets.
    Real secrets are long random strings; placeholders are short descriptive words.
    """
    env_example = Path(".env.example").read_text()
    for line in env_example.splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        # Real secrets are typically 20+ chars of random-looking alphanumeric
        # Placeholders look like "your_client_id" or "your_password"
        assert len(val) < 50 or " " in val or "your" in val.lower(), (
            f".env.example line looks like a real secret: {key}=..."
        )


def test_scorer_does_not_import_credentials():
    """scorer.py must be importable without any env vars set."""
    import importlib
    env_backup = {k: os.environ.pop(k, None) for k in FAKE_CREDS}
    try:
        import scorer
        importlib.reload(scorer)
    finally:
        for k, v in env_backup.items():
            if v is not None:
                os.environ[k] = v


def test_poll_seen_file_contains_only_comment_ids(tmp_path, monkeypatch):
    """seen_comments.txt must store only opaque Reddit comment IDs, not usernames or content."""
    import poll

    monkeypatch.chdir(tmp_path)

    test_ids = {"abc123", "def456", "ghi789"}
    seen = set(test_ids)
    poll.save_seen(seen)

    content = (tmp_path / "seen_comments.txt").read_text()
    # IDs should be short alphanumeric strings, not anything resembling credentials or usernames
    for line in content.splitlines():
        assert len(line) <= 20, f"seen_comments line too long (not a comment ID?): {line}"
        assert line.isalnum(), f"seen_comments line has unexpected chars: {line}"
    _assert_no_creds_in_text(content)
