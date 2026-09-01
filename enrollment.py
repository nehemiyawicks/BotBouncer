import re
import logging

import db

log = logging.getLogger(__name__)

CMD_ENROLL = re.compile(r'^!enroll\s+r/(\w+)', re.IGNORECASE)
CMD_STOP = re.compile(r'^!stop\s+r/(\w+)', re.IGNORECASE)
# Supports both modmail format (!whitelist username) and DM format (!whitelist r/sub u/username)
CMD_WHITELIST_DM = re.compile(r'^!whitelist\s+r/(\w+)\s+u/(\w+)', re.IGNORECASE)
CMD_WHITELIST_MODMAIL = re.compile(r'^!whitelist\s+u?/?(\w+)$', re.IGNORECASE)
CMD_DISMISS = re.compile(r'^!dismiss\s+(\w+)', re.IGNORECASE)
CMD_THRESHOLD = re.compile(r'^!threshold\s+r/(\w+)\s+(\d+)', re.IGNORECASE)
CMD_STATUS = re.compile(r'^!status', re.IGNORECASE)


def _is_mod(reddit, username, subreddit):
    try:
        mods = reddit.subreddit(subreddit).moderator()
        return any(m.name.lower() == username.lower() for m in mods)
    except Exception:
        return False


def _reply(message, text):
    try:
        message.reply(text)
    except Exception as e:
        log.warning(f"Failed to reply to {message.author}: {e}")


def _subreddit_for_message(message):
    """Try to determine the subreddit from a modmail message context."""
    try:
        if hasattr(message, "subreddit") and message.subreddit:
            return str(message.subreddit)
    except Exception:
        pass
    return None


def process_inbox(reddit):
    try:
        for message in reddit.inbox.unread(limit=50):
            if not hasattr(message, "body"):
                message.mark_read()
                continue

            body = message.body.strip()
            author = str(message.author) if message.author else ""

            if not author:
                message.mark_read()
                continue

            # !enroll r/sub -- from mod via DM
            m = CMD_ENROLL.match(body)
            if m:
                sub = m.group(1)
                if _is_mod(reddit, author, sub):
                    db.enroll_sub(sub)
                    _reply(message, f"r/{sub} enrolled. BotBouncer is now monitoring.")
                    log.info(f"Enrolled r/{sub} by u/{author}")
                else:
                    _reply(message, f"You are not a mod of r/{sub}.")
                message.mark_read()
                continue

            # !stop r/sub
            m = CMD_STOP.match(body)
            if m:
                sub = m.group(1)
                if _is_mod(reddit, author, sub):
                    db.remove_sub(sub)
                    _reply(message, f"r/{sub} removed from monitoring.")
                else:
                    _reply(message, f"You are not a mod of r/{sub}.")
                message.mark_read()
                continue

            # !whitelist r/sub u/username -- DM format
            m = CMD_WHITELIST_DM.match(body)
            if m:
                sub, user = m.group(1), m.group(2)
                if _is_mod(reddit, author, sub):
                    db.whitelist_user(sub, user)
                    _reply(message, f"u/{user} whitelisted in r/{sub}.")
                else:
                    _reply(message, f"You are not a mod of r/{sub}.")
                message.mark_read()
                continue

            # !whitelist username -- modmail reply format (sub inferred from message context)
            m = CMD_WHITELIST_MODMAIL.match(body)
            if m:
                user = m.group(1)
                sub = _subreddit_for_message(message)
                if sub:
                    if _is_mod(reddit, author, sub):
                        db.whitelist_user(sub, user)
                        _reply(message, f"u/{user} whitelisted in r/{sub}.")
                    else:
                        _reply(message, f"You are not a mod of r/{sub}.")
                else:
                    _reply(message, "Could not determine subreddit. Use: !whitelist r/subname u/username")
                message.mark_read()
                continue

            # !dismiss comment_id -- modmail reply format
            m = CMD_DISMISS.match(body)
            if m:
                comment_id = m.group(1)
                sub = _subreddit_for_message(message)
                if sub and _is_mod(reddit, author, sub):
                    db.dismiss_comment(comment_id)
                    _reply(message, f"Comment {comment_id} dismissed.")
                    log.info(f"Dismissed {comment_id} by u/{author} in r/{sub}")
                elif not sub:
                    _reply(message, "Could not verify subreddit context for dismiss.")
                else:
                    _reply(message, f"You are not a mod of r/{sub}.")
                message.mark_read()
                continue

            # !threshold r/sub N
            m = CMD_THRESHOLD.match(body)
            if m:
                sub, threshold = m.group(1), int(m.group(2))
                if _is_mod(reddit, author, sub):
                    db.set_threshold(sub, threshold)
                    _reply(message, f"Threshold for r/{sub} set to {threshold}.")
                else:
                    _reply(message, f"You are not a mod of r/{sub}.")
                message.mark_read()
                continue

            # !status
            if CMD_STATUS.match(body):
                subs = db.get_enrolled_subs()
                if not subs:
                    _reply(message, "No subreddits enrolled.")
                else:
                    lines = [
                        f"r/{s['subreddit']} (threshold: {s['threshold_override'] or 'default'})"
                        for s in subs
                    ]
                    _reply(message, "Enrolled subreddits:\n" + "\n".join(lines))
                message.mark_read()
                continue

            message.mark_read()

    except Exception as e:
        log.error(f"Inbox processing error: {e}")
