import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import time

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import db

COMMENTS = [
    {
        "id": "ai001",
        "body": (
            "Certainly! It is worth noting that there are several key factors here.\n\n"
            "- First consideration that is relevant to this topic\n"
            "- Second consideration with further elaboration\n"
            "- Third consideration that concludes the analysis\n\n"
            "In conclusion, the evidence supports this approach comprehensively. "
            "To summarize, stakeholders must evaluate these factors with great care. "
            "Key takeaways include the need for structured systematic deliberate analysis. "
            "I hope this helps clarify the situation for your consideration today."
        ),
        "subreddit": "testSub",
        "author": "newbot",
        "permalink": "/r/testSub/comments/ai001",
        "author_age_days": 3,
        "author_karma": 10,
        "author_history": ["word " * 210] * 5,
        "expected_flag": True,
    },
    {
        "id": "human001",
        "body": "lol yeah same happened to me tbh. ngl it was rough",
        "subreddit": "testSub",
        "author": "regualruser",
        "permalink": "/r/testSub/comments/human001",
        "author_age_days": 500,
        "author_karma": 8000,
        "author_history": ["short", "lol", "nah", "same", "ok"],
        "expected_flag": False,
    },
    {
        "id": "ai002",
        "body": (
            "Great question! As an AI I would suggest considering these aspects:\n\n"
            "**Overview:**\nThe situation requires careful analysis.\n\n"
            "**Key Points:**\nFirst point here. Second point here. Third point.\n\n"
            "I would be happy to elaborate further. Feel free to ask follow-up questions. "
            "Does that help clarify things for you today?"
        ),
        "subreddit": "testSub",
        "author": "aispammer",
        "permalink": "/r/testSub/comments/ai002",
        "author_age_days": 5,
        "author_karma": 20,
        "author_history": ["word " * 210] * 10,
        "expected_flag": True,
    },
    {
        "id": "human002",
        "body": "i dont know man, when i was in college this shit was confusing af",
        "subreddit": "testSub",
        "author": "colligeuser",
        "permalink": "/r/testSub/comments/human002",
        "author_age_days": 1200,
        "author_karma": 15000,
        "author_history": ["lmao", "short", "ok", "nah"],
        "expected_flag": False,
    },
]


def make_mock_comment(data):
    comment = MagicMock()
    comment.id = data["id"]
    comment.body = data["body"]
    comment.subreddit = MagicMock()
    comment.subreddit.__str__ = lambda self: data["subreddit"]
    comment.author = MagicMock()
    comment.author.__str__ = lambda self: data["author"]
    comment.permalink = data["permalink"]
    return comment


def make_mock_redditor(data):
    redditor = MagicMock()
    redditor.created_utc = time.time() - data["author_age_days"] * 86400
    redditor.comment_karma = data["author_karma"]
    comments = []
    for h in data["author_history"]:
        c = MagicMock()
        c.body = h
        comments.append(c)
    redditor.comments.new.return_value = comments
    return redditor


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "integration_test.db")
    db.init_db()
    db.enroll_sub("testSub")
    yield


def test_integration_stream():
    import bot as bot_module
    import mailer

    mock_reddit = MagicMock()

    redditor_map = {d["author"]: make_mock_redditor(d) for d in COMMENTS}
    mock_reddit.redditor.side_effect = lambda name: redditor_map.get(name, MagicMock())

    mock_comments = [make_mock_comment(d) for d in COMMENTS]

    with patch.object(mailer, "send_flag_modmail", return_value=True) as mock_mail, \
         patch.object(mailer, "send_escalated_modmail") as mock_escalated, \
         patch("time.sleep"):

        from scorer import CommentScorer
        scorer = CommentScorer()
        config = {
            "default": {"threshold": 20, "max_comment_length_to_score": 5000,
                        "account_cache_ttl_hours": 24, "modmail_cooldown_minutes": 0}
        }

        for data, comment in zip(COMMENTS, mock_comments):
            info = {
                "age_days": data["author_age_days"],
                "karma": data["author_karma"],
                "comment_history": data["author_history"],
            }
            result = scorer.score(comment.body, info["age_days"], info["karma"], info["comment_history"])

            username = data["author"]
            subreddit = data["subreddit"]

            if result.verdict == "flag" and result.total_score >= 20:
                flag_count = db.log_flagged_comment(
                    comment.id, subreddit, username,
                    result.total_score, result.signals_triggered, result.verdict,
                )
                mailer.send_flag_modmail(
                    mock_reddit, subreddit, username,
                    info["age_days"], info["karma"],
                    f"https://reddit.com{comment.permalink}",
                    result.total_score, result.signals_triggered,
                    comment.body, comment.id, 0,
                )

    expected_flags = sum(1 for d in COMMENTS if d["expected_flag"])
    assert mock_mail.call_count == expected_flags, (
        f"Expected {expected_flags} modmail calls, got {mock_mail.call_count}"
    )

    with db._conn() as con:
        rows = con.execute("SELECT * FROM flagged_comments").fetchall()
    assert len(rows) == expected_flags

    flagged_ids = {r["comment_id"] for r in rows}
    for data in COMMENTS:
        if data["expected_flag"]:
            assert data["id"] in flagged_ids, f"{data['id']} should be flagged"
        else:
            assert data["id"] not in flagged_ids, f"{data['id']} should NOT be flagged"
