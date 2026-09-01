import json
import os
import time
import logging
import logging.handlers

import praw
import yaml
from dotenv import load_dotenv

import db
import mailer
import enrollment
from scorer import CommentScorer

load_dotenv()

log = logging.getLogger("botbouncer")
log.setLevel(logging.INFO)
handler = logging.handlers.RotatingFileHandler("bot.log", maxBytes=5 * 1024 * 1024, backupCount=3)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(handler)
log.addHandler(logging.StreamHandler())


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        log.error(f"Required environment variable {name} is not set. See .env.example.")
        raise SystemExit(1)
    return val


def make_reddit():
    return praw.Reddit(
        client_id=_require_env("REDDIT_CLIENT_ID"),
        client_secret=_require_env("REDDIT_CLIENT_SECRET"),
        username=_require_env("REDDIT_USERNAME"),
        password=_require_env("REDDIT_PASSWORD"),
        user_agent=os.environ.get("REDDIT_USER_AGENT", "BotBouncer/1.0"),
    )


def fetch_account_info(reddit, username, ttl_hours):
    cached = db.get_cached_account(username, ttl_hours)
    if cached:
        return cached

    try:
        user = reddit.redditor(username)
        created = user.created_utc
        age_days = int((time.time() - created) / 86400)
        karma = user.comment_karma
        # Fetch all 10 comments in one batch -- no per-item sleep inside this loop
        comments = [c.body for c in user.comments.new(limit=10)]
        db.cache_account(username, age_days, karma, comments)
        return {"age_days": age_days, "karma": karma, "comment_history": comments}
    except Exception as e:
        log.warning(f"Could not fetch account info for {username}: {e}")
        return {"age_days": 365, "karma": 1000, "comment_history": []}


def get_sub_config(config, subreddit, enrolled_row=None):
    defaults = config.get("default", {})
    sub_cfg = config.get("subreddits", {}).get(f"r/{subreddit}", {}) or {}
    threshold = sub_cfg.get("threshold", defaults.get("threshold", 20))
    custom_phrases = sub_cfg.get("custom_ai_phrases", [])
    whitelisted = set(sub_cfg.get("whitelisted_users", []))

    if enrolled_row:
        if enrolled_row.get("threshold_override"):
            threshold = enrolled_row["threshold_override"]
        whitelisted |= set(json.loads(enrolled_row.get("whitelisted_users") or "[]"))
        custom_phrases += json.loads(enrolled_row.get("custom_phrases") or "[]")

    return threshold, custom_phrases, whitelisted


def exponential_backoff(attempt):
    wait = min(60 * (2 ** attempt), 3600)
    log.warning(f"Backing off for {wait}s (attempt {attempt})")
    time.sleep(wait)


def run():
    db.init_db()
    config = load_config()
    reddit = make_reddit()
    scorer = CommentScorer()

    defaults = config.get("default", {})
    ttl_hours = defaults.get("account_cache_ttl_hours", 24)
    cooldown = defaults.get("modmail_cooldown_minutes", 60)
    max_length = defaults.get("max_comment_length_to_score", 5000)

    inbox_last_check = 0
    error_count = 0

    while True:
        try:
            enrolled = db.get_enrolled_subs()
            if not enrolled:
                log.info("No enrolled subreddits. Checking inbox...")
                if time.time() - inbox_last_check > 60:
                    enrollment.process_inbox(reddit)
                    inbox_last_check = time.time()
                time.sleep(10)
                continue

            sub_names = "+".join(s["subreddit"] for s in enrolled)
            multi = reddit.subreddit(sub_names)

            for comment in multi.stream.comments(skip_existing=True):
                # Refresh enrolled list and check inbox periodically
                if time.time() - inbox_last_check > 60:
                    enrollment.process_inbox(reddit)
                    inbox_last_check = time.time()
                    enrolled = db.get_enrolled_subs()

                try:
                    if not comment.author:
                        continue

                    username = str(comment.author)
                    subreddit = str(comment.subreddit)
                    body = comment.body

                    if len(body.split()) > max_length:
                        continue

                    enrolled_row = next(
                        (s for s in enrolled if s["subreddit"] == subreddit), None
                    )
                    threshold, custom_phrases, whitelisted = get_sub_config(
                        config, subreddit, enrolled_row
                    )

                    if username in whitelisted:
                        continue

                    info = fetch_account_info(reddit, username, ttl_hours)
                    result = scorer.score(
                        body,
                        info["age_days"],
                        info["karma"],
                        info["comment_history"],
                    )

                    log.info(
                        f"{subreddit} | {username} | score={result.total_score} verdict={result.verdict}"
                    )

                    if result.verdict == "flag" and result.total_score >= threshold:
                        flag_count = db.log_flagged_comment(
                            comment.id, subreddit, username,
                            result.total_score, result.signals_triggered, result.verdict,
                        )

                        mailer.send_flag_modmail(
                            reddit, subreddit, username,
                            info["age_days"], info["karma"],
                            f"https://reddit.com{comment.permalink}",
                            result.total_score, result.signals_triggered,
                            body, comment.id, cooldown,
                        )

                        # Only escalate once per user (check escalated flag in DB)
                        if flag_count >= 3 and not db.is_escalated(username):
                            flags = db.get_user_flags(username)
                            permalinks = [
                                f"https://reddit.com/r/{f['subreddit']}/comments/{f['comment_id']}"
                                for f in flags[:5]
                            ]
                            db.mark_escalated(username)
                            mailer.send_escalated_modmail(
                                reddit, subreddit, username, flag_count, permalinks
                            )

                    time.sleep(1)
                    error_count = 0

                except praw.exceptions.APIException as e:
                    log.error(f"API error: {e}")
                    if "429" in str(e) or "RATELIMIT" in str(getattr(e, "error_type", "")):
                        exponential_backoff(error_count)
                        error_count += 1
                except Exception as e:
                    log.error(f"Comment processing error: {e}")

        except Exception as e:
            log.error(f"Stream error: {e}")
            exponential_backoff(error_count)
            error_count = min(error_count + 1, 6)


if __name__ == "__main__":
    run()
