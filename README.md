# BotBouncer

**This bot assists moderators, it does not replace them.**

A Reddit bot that detects AI-generated comments and alerts moderators via modmail. Not a keyword filter -- it scores comments across behavioral, linguistic, and account signals, the same way a trained human mod would spot AI slop.

GitHub Sponsors: https://github.com/sponsors/nehemiyawicks

---

## What it does

- Monitors enrolled subreddits for comments that look AI-generated
- Scores each comment across 5 signal groups (phrase patterns, structure, account history, statistics, human penalties)
- Sends a modmail alert when a comment crosses the threshold
- Escalates repeat offenders (3+ flags) with a separate modmail
- Never auto-removes or auto-bans anything

## What it does not do

- No auto-remove or auto-ban
- No keyword blacklists
- No paid API calls (no OpenAI, no Anthropic)
- No web dashboard
- No Docker

---

## Hosting options

### Option 1: GitHub Actions (free, zero infrastructure)

Fork this repo and it runs on GitHub's servers for free. Works by polling Reddit every 15 minutes instead of streaming.

**Setup:**

1. Fork this repo
2. Create a Reddit script app at reddit.com/prefs/apps (select "script", redirect URI = `http://localhost:8080`)
3. Go to your fork's Settings > Secrets and variables > Actions
4. Add these **Secrets**:
   - `REDDIT_CLIENT_ID` -- from your Reddit app
   - `REDDIT_CLIENT_SECRET` -- from your Reddit app
   - `REDDIT_USERNAME` -- your bot account username
   - `REDDIT_PASSWORD` -- your bot account password
   - `MONITOR_SUBS` -- comma-separated subreddit names, e.g. `python,learnpython,programming`
5. Go to Actions tab and enable workflows
6. The bot runs automatically every 15 minutes

To change the flag threshold, add a **Variable** (not secret) named `SCORE_THRESHOLD` with a value like `25`.

To trigger a manual run: Actions > BotBouncer > Run workflow.

**Limits:** GitHub gives 2000 free minutes/month on public repos. At 15-min intervals, this bot uses ~2 min/run * 2880 runs/month = well under the limit for a handful of subreddits.

---

### Option 2: Self-host on Oracle Cloud Free Tier (persistent streaming)

Oracle Cloud's always-free ARM VM (4 cores, 24GB RAM) runs indefinitely at no cost.

1. Create an account at cloud.oracle.com, spin up an ARM Ampere A1 instance with Ubuntu 22.04
2. SSH in and set up:
   ```
   sudo apt update && sudo apt install python3.11 python3.11-venv git -y
   git clone https://github.com/nehemiyawicks/BotBouncer
   cd BotBouncer
   python3.11 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env && nano .env
   ```
3. Run with systemd for auto-restart:
   ```
   sudo nano /etc/systemd/system/botbouncer.service
   ```
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
   ```
   sudo systemctl enable --now botbouncer
   ```

This mode uses `bot.py` (persistent stream) instead of `poll.py` and handles enrollment via DMs.

---

### Option 3: Your own VPC

Same as Oracle Cloud above -- just run `bot.py` as a systemd service on any Linux machine. All it needs is Python 3.11+ and outbound HTTPS.

---

## Enrolling your subreddit

**GitHub Actions mode:** add your subreddit to the `MONITOR_SUBS` secret in your fork. No DMs needed.

**Self-hosted mode:** DM the bot account with:
```
!enroll r/yoursubreddit
```
You must be a moderator. The bot verifies this before acting.

Other commands:
- `!stop r/yoursubreddit` - stop monitoring
- `!whitelist r/yoursubreddit u/username` - whitelist a user
- `!threshold r/yoursubreddit 25` - custom score threshold
- `!status` - list enrolled subreddits

---

## Score breakdown

| Group | What it checks | Points |
|-------|---------------|--------|
| A - AI phrases | "Certainly!", "In conclusion", "Key takeaways", "it is important to", etc. | up to +15 |
| B - Structure | Bullet lists, bold headers, em dashes, no contractions, no opinion markers, uniform paragraphs, definition-style opener, transitional overuse, explanatory connectors | up to +27 |
| C - Account | New account, low karma, all-long comment history, no casual comments | up to +17 |
| D - Statistics | High lexical diversity, low sentence variance, high readability grade | up to +9 |
| E - Human signals | Profanity, typos, Reddit slang, personal anecdotes, short comments | up to -17 |

Thresholds:
- score < 10: clean, no action
- score 10-19: suspicious, logged only
- score >= 20: flagged, modmail sent (default; configurable per sub)

Detection rates (validated against HC3 reddit_eli5 dataset):
- AI detection (>=10): 100%
- AI flag rate (>=20): 70%
- Human false positive rate (>=20): 0%

---

## Test data setup

```
pip install -r requirements-dev.txt
python scripts/prepare_test_data.py
pytest tests/ -v
```

This downloads the HC3 reddit_eli5 split from HuggingFace (Hello-SimpleAI/HC3) and saves 500 AI + 500 human samples to `tests/data/`.

---

## False positive policy

The scorer is tuned for 0% false positive rate on human Reddit comments (validated against the HC3 dataset). A comment is never removed automatically. Mods review every alert and can dismiss or whitelist users directly by replying to the modmail.
