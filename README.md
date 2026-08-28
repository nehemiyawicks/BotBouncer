# BotBouncer

**This bot assists moderators, it does not replace them.**

A Reddit bot that detects AI-generated comments and alerts moderators via modmail. It is not a keyword filter. It scores comments based on a combination of behavioral, linguistic, and account signals -- the same signals a trained human mod would notice.

Supports GitHub Sponsors: https://github.com/sponsors/nehemiyawicks

---

## What it does

- Monitors enrolled subreddits for comments that look AI-generated
- Scores each comment across 5 signal groups (phrase patterns, structure, account history, statistics, human penalties)
- Sends a modmail alert when a comment scores above the threshold
- Escalates repeat offenders (3+ flags) with a separate modmail
- Never auto-removes or auto-bans anything

## What it does not do

- No auto-remove or auto-ban
- No keyword blacklists
- No paid API calls (no OpenAI, no Anthropic)
- No web dashboard
- No Docker

---

## Score breakdown

| Group | What it checks | Max points |
|-------|---------------|-----------|
| A - AI phrases | "Certainly!", "In conclusion", "Key takeaways", etc. | +15 |
| B - Structure | Bullet lists, bold headers, no contractions, em dashes, uniform paragraphs | +24 |
| C - Account | New account, low karma, all-long comment history | +19 |
| D - Statistics | High lexical diversity, low sentence variance, high readability grade | +9 |
| E - Human signals | Profanity, typos, Reddit slang, personal anecdotes, short comments | -17 |

Thresholds:
- score < 10: clean, no action
- score 10-19: suspicious, logged only
- score >= 20: flagged, modmail sent

---

## Enroll your subreddit

DM the bot account (u/BotBouncer) with:

```
!enroll r/yoursubreddit
```

You must be a moderator of the subreddit. The bot verifies this via the Reddit API before acting.

Other commands:
- `!stop r/yoursubreddit` - stop monitoring
- `!whitelist r/yoursubreddit u/username` - whitelist a user
- `!threshold r/yoursubreddit 25` - set a custom score threshold
- `!status` - list enrolled subreddits and stats

---

## Self-host on Oracle Cloud Free Tier

Oracle Cloud gives you a free ARM VM (4 cores, 24GB RAM) that runs indefinitely.

1. Create an account at cloud.oracle.com, spin up an ARM Ampere A1 instance running Ubuntu 22.04
2. SSH in and install Python 3.11+:
   ```
   sudo apt update && sudo apt install python3.11 python3.11-venv git -y
   ```
3. Clone and set up:
   ```
   git clone https://github.com/nehemiyawicks/BotBouncer
   cd BotBouncer
   python3.11 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```
4. Edit `.env` with your Reddit app credentials (create a script-type app at reddit.com/prefs/apps)
5. Run:
   ```
   nohup python bot.py > /dev/null 2>&1 &
   ```
6. Or use systemd for auto-restart on reboot -- create `/etc/systemd/system/botbouncer.service`:
   ```ini
   [Unit]
   Description=BotBouncer
   After=network.target

   [Service]
   User=ubuntu
   WorkingDirectory=/home/ubuntu/BotBouncer
   ExecStart=/home/ubuntu/BotBouncer/venv/bin/python bot.py
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
   Then: `sudo systemctl enable --now botbouncer`

---

## Test data

Tests require sample data from the HC3 dataset (Human ChatGPT Comparison Corpus).

```
pip install -r requirements-dev.txt
python scripts/prepare_test_data.py
```

This downloads the `reddit_eli5` split from HuggingFace (Hello-SimpleAI/HC3) and saves 500 AI samples + 500 human samples to `tests/data/`.

Run tests:
```
pytest tests/ -v --cov=.
```

---

## Reddit app setup

1. Go to reddit.com/prefs/apps
2. Create a new app, select "script"
3. Set redirect URI to `http://localhost:8080`
4. Copy client ID and secret into `.env`

---

## False positive policy

The scorer is tuned for <= 5% false positive rate on human Reddit comments (validated against the HC3 dataset). A comment is never removed automatically. Mods review every alert and can dismiss or whitelist users directly by replying to the modmail.
