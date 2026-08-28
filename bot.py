import os
import time
import logging
import logging.handlers
from datetime import datetime, timezone

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


def make_reddit():
    return praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        username=os.environ["REDDIT_USERNAME"],
        password=os.environ["REDDIT_PASSWORD"],
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
        comments = []
        for c in user.comments.new(limit=10):
            comments.append(c.body)
            time.sleep(0.5)
        db.cache_account(username, age_days, karma, comments)
        return {"age_days": age_days, "karma": karma, "comment_history": comments}
    except Exception as e:
        log.warning(f"Could not fetch account info for {username}: {e}")
        return {"age_days": 365, "karma": 1000, "comment_history": []}


def get_sub_config(config, subreddit):
    defaults = config.get("default", {})
    sub_cfg = config.get("subreddits", {}).get(f"r/{subreddit}", {})
    threshold = sub_cfg.get("threshold", defaults.get("threshold", 20))
    custom_phrases = sub_cfg.get("custom_ai_phrases", [])
    whitelisted = sub_cfg.get("whitelisted_users", [])
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
                if time.time() - inbox_last_check > 60:
                    enrollment.process_inbox(reddit)
                    inbox_last_check = time.time()

                try:
                    if not comment.author:
                        continue

                    username = str(comment.author)
                    subreddit = str(comment.subreddit)
                    body = comment.body

                    if len(body.split()) > max_length:
                        continue

                    threshold, custom_phrases, whitelisted = get_sub_config(config, subreddit)

                    if username in whitelisted:
                        continue

                    # check db whitelist
                    enrolled_row = next(
                        (s for s in enrolled if s["subreddit"] == subreddit), None
                    )
                    if enrolled_row:
                        import json
                        db_whitelist = json.loads(enrolled_row.get("whitelisted_users") or "[]")
                        if username in db_whitelist:
                            continue
                        if enrolled_row.get("threshold_override"):
                            threshold = enrolled_row["threshold_override"]

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

                        if flag_count >= 3:
                            flags = db.get_user_flags(username)
                            permalinks = [f.get("comment_id", "") for f in flags[:5]]
                            db.mark_escalated(username)
                            mailer.send_escalated_modmail(
                                reddit, subreddit, username, flag_count, permalinks
                            )

                    time.sleep(1)
                    error_count = 0

                except praw.exceptions.APIException as e:
                    log.error(f"API error: {e}")
                    if "429" in str(e) or "RATELIMIT" in str(e.error_type):
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
