# Oil Fundamental Alert Bot for Telegram

A Telegram bot that watches oil / macro / war-related headlines, scores them for WTI/Brent, and sends only high-conviction alerts.

## Features
- Telegram commands for control
- Scheduled polling with JobQueue
- Oil headline classification: Bullish / Bearish / Neutral
- Confidence score 1-10
- De-duplication of repeated headlines
- Alert threshold filtering
- Per-chat subscription preferences
- War / sanctions / outage / OPEC / inventories / PMI / GDP / CPI weighting
- Dry, readable alert format ready for trading use

## Commands
- `/start` - welcome + status
- `/help` - command list
- `/watch on` - subscribe this chat
- `/watch off` - unsubscribe this chat
- `/status` - current bot settings for this chat
- `/setthreshold 7` - set alert threshold 1-10 for this chat
- `/now` - run one analysis immediately
- `/testalert` - send a sample alert

## Setup
1. Create a bot with BotFather and copy the bot token.
2. Copy `.env.example` to `.env`.
3. Fill in `TELEGRAM_BOT_TOKEN`.
4. Optional: set `ALLOWED_CHAT_IDS` to a comma-separated allowlist.
5. Install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
6. Run:
   ```bash
   python bot.py
   ```

## Notes
- Default polling interval is 300 seconds.
- Default alert threshold is 7/10.
- Headlines are pulled from built-in Google News RSS searches unless you provide your own feeds.
- The bot stores subscriptions and dedupe history in `state.json`.

## Deployment
- Local machine
- VPS
- Railway / Render / Fly.io / Docker
- AWS EC2: see `deploy/EC2.md`

## Safety
This bot sends alerts only. It does not place trades.
