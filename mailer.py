import time

BOT_NAME = "BotBouncer"
SPONSORS_URL = "https://github.com/sponsors/nehemiyawicks"

_last_sent: dict[str, float] = {}


def _cooldown_ok(subreddit: str, cooldown_minutes: int) -> bool:
    last = _last_sent.get(subreddit, 0)
    return (time.time() - last) >= cooldown_minutes * 60


def send_flag_modmail(reddit, subreddit: str, username: str, age_days: int, karma: int,
                      permalink: str, score: int, signals: list[str], excerpt: str,
                      comment_id: str, cooldown_minutes: int = 60):
    if not _cooldown_ok(subreddit, cooldown_minutes):
        return False

    signals_formatted = "\n".join(f"  - {s}" for s in signals)
    subject = "[AI Content Alert] Suspicious comment detected"
    body = (
        f"User: u/{username} (account age: {age_days} days, karma: {karma})\n"
        f"Comment: {permalink}\n"
        f"Score: {score}/40\n\n"
        f"Signals triggered:\n{signals_formatted}\n\n"
        f'Excerpt: "{excerpt[:150]}..."\n\n'
        f"This is an automated flag for human review.\n"
        f'To dismiss: reply "!dismiss {comment_id}" to this message.\n'
        f'To whitelist this user: reply "!whitelist {username}".\n\n'
        f"Powered by {BOT_NAME} | {SPONSORS_URL}"
    )

    sub = reddit.subreddit(subreddit)
    sub.message(subject, body)
    _last_sent[subreddit] = time.time()
    return True


def send_escalated_modmail(reddit, subreddit: str, username: str, flag_count: int,
                           permalinks: list[str]):
    links = "\n".join(f"  - {p}" for p in permalinks)
    subject = "[ESCALATED - Repeat Offender]"
    body = (
        f"u/{username} has been flagged {flag_count} times across your subreddit.\n\n"
        f"Previous flags:\n{links}\n\n"
        f"Consider reviewing their comment history manually.\n\n"
        f"Powered by {BOT_NAME} | {SPONSORS_URL}"
    )
    sub = reddit.subreddit(subreddit)
    sub.message(subject, body)
