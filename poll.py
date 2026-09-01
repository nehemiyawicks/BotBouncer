"""
Stateless polling mode for GitHub Actions.

Runs once, checks the last 15 minutes of comments across enrolled subs,
flags any that score above threshold, then exits. Duplicate detection is
handled by a seen_comments.txt file that GitHub Actions caches between runs.
"""

import os
import time
import logging
import sys
from pathlib import Path

import praw
import yaml
from dotenv import load_dotenv

from scorer import CommentScorer
import mailer

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("poll")

SEEN_FILE = Path("seen_comments.txt")
LOOKBACK_SECONDS = 20 * 60  # 20 min to overlap with 15-min cron cadence


def load_seen():
    if SEEN_FILE.exists():
        ids = set(SEEN_FILE.read_text().splitlines())
        # keep last 5000 IDs to avoid unbounded growth
        return set(list(ids)[-5000:])
    return set()


def save_seen(seen: set):
    ids = list(seen)[-5000:]
    SEEN_FILE.write_text("\n".join(ids))


def make_reddit():
    return praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        username=os.environ["REDDIT_USERNAME"],
        password=os.environ["REDDIT_PASSWORD"],
        user_agent=os.environ.get("REDDIT_USER_AGENT", "BotBouncer/1.0"),
    )


def get_enrolled_subs(reddit) -> list[dict]:
    """
    Reads subs from two sources (in priority order):
    1. MONITOR_SUBS env var (comma-separated) -- used by GitHub Actions secrets
    2. config.yaml subreddits section
    """
    subs = []

    env_subs = os.environ.get("MONITOR_SUBS", "")
    if env_subs:
        for name in env_subs.split(","):
            name = name.strip().lstrip("r/")
            if name:
                subs.append({"subreddit": name, "threshold": None, "whitelisted_users": []})
        return subs

    try:
        with open("config.yaml") as f:
            cfg = yaml.safe_load(f)
        for sub_name, sub_cfg in (cfg.get("subreddits") or {}).items():
            name = sub_name.lstrip("r/")
            subs.append({
                "subreddit": name,
                "threshold": (sub_cfg or {}).get("threshold"),
                "whitelisted_users": (sub_cfg or {}).get("whitelisted_users", []),
            })
    except FileNotFoundError:
        pass

    return subs


def fetch_account_info(reddit, username: str) -> dict:
    try:
        user = reddit.redditor(username)
        age_days = int((time.time() - user.created_utc) / 86400)
        karma = user.comment_karma
        history = [c.body for c in user.comments.new(limit=10)]
        return {"age_days": age_days, "karma": karma, "comment_history": history}
    except Exception as e:
        log.warning(f"Could not fetch {username}: {e}")
        return {"age_days": 365, "karma": 1000, "comment_history": []}


def run():
    try:
        with open("config.yaml") as f:
            cfg = yaml.safe_load(f)
    except FileNotFoundError:
        cfg = {}

    defaults = cfg.get("default", {})
    default_threshold = int(os.environ.get("SCORE_THRESHOLD", defaults.get("threshold", 20)))
    max_len = defaults.get("max_comment_length_to_score", 5000)

    reddit = make_reddit()
    scorer = CommentScorer()
    seen = load_seen()
    cutoff = time.time() - LOOKBACK_SECONDS
    flagged_count = 0

    enrolled = get_enrolled_subs(reddit)
    if not enrolled:
        log.warning("No subreddits configured. Set MONITOR_SUBS secret or add to config.yaml.")
        sys.exit(0)

    log.info(f"Polling {len(enrolled)} subreddit(s): {[s['subreddit'] for s in enrolled]}")

    for sub_info in enrolled:
        sub_name = sub_info["subreddit"]
        threshold = sub_info.get("threshold") or default_threshold
        whitelisted = set(sub_info.get("whitelisted_users") or [])

        try:
            sub = reddit.subreddit(sub_name)
            for comment in sub.comments(limit=100):
                if comment.created_utc < cutoff:
                    break
                if comment.id in seen:
                    continue
                if not comment.author:
                    continue

                username = str(comment.author)
                if username in whitelisted:
                    seen.add(comment.id)
                    continue

                body = comment.body
                if len(body.split()) > max_len:
                    seen.add(comment.id)
                    continue

                info = fetch_account_info(reddit, username)
                result = scorer.score(body, info["age_days"], info["karma"], info["comment_history"])

                log.info(f"r/{sub_name} | {username} | score={result.total_score} verdict={result.verdict}")

                if result.verdict == "flag" and result.total_score >= threshold:
                    sent = mailer.send_flag_modmail(
                        reddit, sub_name, username,
                        info["age_days"], info["karma"],
                        f"https://reddit.com{comment.permalink}",
                        result.total_score, result.signals_triggered,
                        body, comment.id,
                        cooldown_minutes=0,  # Actions runs are already rate-limited by cron
                    )
                    if sent:
                        flagged_count += 1
                        log.info(f"Flagged {username} in r/{sub_name} (score={result.total_score})")

                seen.add(comment.id)
                time.sleep(0.5)  # stay under API rate limit

        except Exception as e:
            log.error(f"Error polling r/{sub_name}: {e}")

    save_seen(seen)
    log.info(f"Done. Flagged {flagged_count} comment(s) this run.")


if __name__ == "__main__":
    run()
