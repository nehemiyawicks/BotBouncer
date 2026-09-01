"""
Live integration test runner. Not part of the pytest suite -- run manually.

Modes:
  python test_live.py --auth          Check credentials connect to Reddit
  python test_live.py --score         Score hardcoded comments, print results
  python test_live.py --poll          Run one poll cycle (reads real comments, no modmail sent)
  python test_live.py --post-test     Post a synthetic AI comment to MONITOR_SUBS and verify it flags
                                      (requires a single sub in MONITOR_SUBS and mod access)
  python test_live.py --modmail-test  Send a real test modmail to MONITOR_SUBS to verify delivery
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Sample comments for --score mode
# ---------------------------------------------------------------------------

SAMPLES = [
    {
        "label": "AI (should flag)",
        "text": (
            "It is important to note that cryptocurrency markets are highly volatile. "
            "There are several key factors to consider when evaluating investment opportunities. "
            "Additionally, regulatory frameworks vary significantly across jurisdictions. "
            "Furthermore, liquidity constraints can impact portfolio rebalancing strategies. "
            "In conclusion, a diversified approach is recommended to mitigate systemic risk. "
            "I hope this helps clarify the situation for your consideration."
        ),
        "account_age_days": 5,
        "karma": 30,
        "history": ["word " * 210] * 8,
    },
    {
        "label": "Human (should be clean)",
        "text": "lol same, happened to my roommate last year. ngl it was a nightmare to sort out tbh",
        "account_age_days": 800,
        "karma": 12000,
        "history": ["short", "lmao yeah", "nah", "same"],
    },
    {
        "label": "AI ELI5 style (should flag)",
        "text": (
            "Photosynthesis is the process by which plants convert light energy into chemical energy. "
            "This is because chlorophyll molecules absorb sunlight and use it to drive chemical reactions. "
            "The process can be divided into two main stages: the light-dependent reactions and the "
            "light-independent reactions. The reason for this distinction is that the first stage "
            "requires direct sunlight while the second stage can occur in the absence of light. "
            "Overall, it is a fundamental biological process that sustains nearly all life on Earth."
        ),
        "account_age_days": 12,
        "karma": 45,
        "history": ["word " * 210] * 10,
    },
    {
        "label": "Long human (should be suspicious or clean)",
        "text": (
            "I worked in finance for 8 years and honestly this is way more complicated than people think. "
            "When I was at my old firm we had a whole team just for this and they still got it wrong half "
            "the time. My boss used to say don't trust any model you didn't break yourself. "
            "The real problem isn't the math, it's that nobody agrees on the assumptions going in. "
            "You can get wildly different answers depending on what you plug in. "
            "Anyway just my two cents, imo the academic literature on this is pretty detached from reality."
        ),
        "account_age_days": 1200,
        "karma": 8500,
        "history": ["short lol", "nah", "idk man", "word " * 210, "same"],
    },
]


def run_score():
    from scorer import CommentScorer
    scorer = CommentScorer()
    print("\n" + "=" * 70)
    print("SCORER TEST (no Reddit connection needed)")
    print("=" * 70)
    for s in SAMPLES:
        result = scorer.score(s["text"], s["account_age_days"], s["karma"], s["history"])
        verdict_display = {
            "clean": "CLEAN    ",
            "suspicious": "SUSPICIOUS",
            "flag": "FLAG     ",
        }[result.verdict]
        print(f"\n[{verdict_display}] score={result.total_score:>3}  {s['label']}")
        print(f"  Signals: {', '.join(result.signals_triggered) or 'none'}")
    print()


def run_auth():
    import praw
    print("\nChecking Reddit credentials...")
    try:
        reddit = praw.Reddit(
            client_id=os.environ["REDDIT_CLIENT_ID"],
            client_secret=os.environ["REDDIT_CLIENT_SECRET"],
            username=os.environ["REDDIT_USERNAME"],
            password=os.environ["REDDIT_PASSWORD"],
            user_agent=os.environ.get("REDDIT_USER_AGENT", "BotBouncer/1.0 test"),
        )
        me = reddit.user.me()
        print(f"  Authenticated as: u/{me.name}")
        print(f"  Account age: {int((time.time() - me.created_utc) / 86400)} days")
        print(f"  Comment karma: {me.comment_karma}")

        monitor = os.environ.get("MONITOR_SUBS", "")
        if monitor:
            for sub_name in monitor.split(","):
                sub_name = sub_name.strip().lstrip("r/")
                try:
                    sub = reddit.subreddit(sub_name)
                    _ = sub.id  # trigger fetch
                    mod_names = [m.name for m in sub.moderator()]
                    is_mod = me.name in mod_names
                    print(f"  r/{sub_name}: accessible, bot is mod: {is_mod}")
                    if not is_mod:
                        print(f"    WARNING: bot is not a mod of r/{sub_name} -- modmail won't work")
                except Exception as e:
                    print(f"  r/{sub_name}: ERROR -- {e}")
        print("\nAuth OK.")
        return reddit
    except Exception as e:
        print(f"Auth FAILED: {e}")
        sys.exit(1)


def run_poll_dryrun():
    import praw
    from scorer import CommentScorer

    reddit = run_auth()
    scorer = CommentScorer()
    monitor = os.environ.get("MONITOR_SUBS", "")
    if not monitor:
        print("Set MONITOR_SUBS in .env to a subreddit name.")
        sys.exit(1)

    cutoff = time.time() - 20 * 60
    print(f"\nDry-run poll (no modmail will be sent)\n{'=' * 50}")

    for sub_name in monitor.split(","):
        sub_name = sub_name.strip().lstrip("r/")
        print(f"\nr/{sub_name} -- last 20 min of comments:")
        try:
            sub = reddit.subreddit(sub_name)
            scored = 0
            would_flag = 0
            for comment in sub.comments(limit=100):
                if comment.created_utc < cutoff:
                    break
                if not comment.author:
                    continue
                username = str(comment.author)
                try:
                    user = reddit.redditor(username)
                    age_days = int((time.time() - user.created_utc) / 86400)
                    karma = user.comment_karma
                    history = [c.body for c in user.comments.new(limit=5)]
                except Exception:
                    age_days, karma, history = 365, 1000, []

                result = scorer.score(comment.body, age_days, karma, history)
                scored += 1
                marker = ""
                if result.verdict == "flag":
                    would_flag += 1
                    marker = " <-- WOULD FLAG"
                elif result.verdict == "suspicious":
                    marker = " <-- suspicious"
                print(f"  u/{username:<20} score={result.total_score:>3} [{result.verdict}]{marker}")
                if result.verdict == "flag":
                    print(f"    signals: {', '.join(result.signals_triggered[:4])}")
                time.sleep(0.5)

            print(f"\n  Scored {scored} comments, would flag {would_flag}")
        except Exception as e:
            print(f"  Error: {e}")


def run_post_test():
    """
    Posts an obvious AI comment to the test sub from the bot account itself,
    then runs a poll to confirm it would be flagged.
    The comment is deleted after the test.
    """
    import praw
    from scorer import CommentScorer

    monitor = os.environ.get("MONITOR_SUBS", "")
    if not monitor or "," in monitor:
        print("Set MONITOR_SUBS to a single subreddit for --post-test.")
        sys.exit(1)
    sub_name = monitor.strip().lstrip("r/")

    reddit = run_auth()
    scorer = CommentScorer()

    AI_COMMENT = (
        "It is important to note that this topic requires careful consideration. "
        "There are several key factors to evaluate when approaching this subject. "
        "Additionally, regulatory and contextual frameworks vary significantly. "
        "Furthermore, a systematic analysis reveals multiple interdependencies. "
        "In conclusion, a nuanced and comprehensive approach is strongly recommended. "
        "Key takeaways include the importance of evidence-based decision making."
    )

    print(f"\nPosting test comment to r/{sub_name}...")
    try:
        sub = reddit.subreddit(sub_name)
        # Find the newest post to comment on
        post = next(sub.new(limit=1))
        comment = post.reply(AI_COMMENT)
        print(f"  Posted: https://reddit.com{comment.permalink}")
        time.sleep(3)

        me = reddit.user.me()
        result = scorer.score(AI_COMMENT, 1, 1, ["word " * 210] * 5)
        print(f"\nScorer result for test comment:")
        print(f"  Score: {result.total_score}  Verdict: {result.verdict}")
        print(f"  Signals: {', '.join(result.signals_triggered)}")

        if result.verdict == "flag":
            print("\nPASS: test comment would be flagged.")
        else:
            print(f"\nFAIL: expected flag, got {result.verdict} (score={result.total_score})")

        comment.delete()
        print("Test comment deleted.")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def run_modmail_test():
    monitor = os.environ.get("MONITOR_SUBS", "")
    if not monitor:
        print("Set MONITOR_SUBS in .env.")
        sys.exit(1)
    sub_name = monitor.split(",")[0].strip().lstrip("r/")

    reddit = run_auth()
    print(f"\nSending test modmail to r/{sub_name} mod team...")
    try:
        import mailer
        mailer._last_sent.clear()  # bypass cooldown for test
        sent = mailer.send_flag_modmail(
            reddit, sub_name,
            username="test_user",
            age_days=3,
            karma=10,
            permalink="https://reddit.com/r/test/comments/abc123",
            score=27,
            signals=[
                "ai_phrase:it is important to",
                "structural:no contractions in long comment",
                "structural:definition-style opener",
                "account:age < 7 days",
                "structural:no personal opinion markers",
            ],
            excerpt="It is important to note that this topic requires careful consideration...",
            comment_id="abc123",
            cooldown_minutes=0,
        )
        if sent:
            print("Modmail sent. Check the mod inbox of r/" + sub_name)
        else:
            print("Modmail not sent (cooldown or error).")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth", action="store_true", help="Check Reddit credentials")
    parser.add_argument("--score", action="store_true", help="Score hardcoded samples offline")
    parser.add_argument("--poll", action="store_true", help="Dry-run poll (no modmail)")
    parser.add_argument("--post-test", action="store_true", help="Post+score+delete a real test comment")
    parser.add_argument("--modmail-test", action="store_true", help="Send a test modmail to verify delivery")
    args = parser.parse_args()

    if not any(vars(args).values()):
        parser.print_help()
        sys.exit(0)

    if args.score:
        run_score()
    if args.auth:
        run_auth()
    if args.poll:
        run_poll_dryrun()
    if args.post_test:
        run_post_test()
    if args.modmail_test:
        run_modmail_test()
