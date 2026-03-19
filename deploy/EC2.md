# Run This Bot on AWS EC2

This project works well on a small Ubuntu EC2 instance because it uses Telegram long polling and does not need inbound web traffic.

## 1. Prepare the EC2 instance

- Use Ubuntu 24.04 or 22.04.
- In the security group, allow inbound `22` only from your own IP.
- You do not need inbound `80` or `443` for this bot.
- Outbound internet access must be allowed so the bot can reach Telegram, RSS feeds, and Investing.com.

## 2. SSH into the server

```bash
ssh -i /path/to/your-key.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

## 3. Install system packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv git
```

## 4. Copy the code onto the server

Clone the repo if it is in GitHub:

```bash
cd /opt
sudo git clone YOUR_REPO_URL oil-telegram-bot
sudo chown -R ubuntu:ubuntu /opt/oil-telegram-bot
cd /opt/oil-telegram-bot
```

Or upload your local project folder to `/opt/oil-telegram-bot`.

## 5. Create the virtual environment and install Python packages

```bash
cd /opt/oil-telegram-bot
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 6. Create the environment file

```bash
cp .env.example .env
nano .env
```

Set at least:

```dotenv
TELEGRAM_BOT_TOKEN=YOUR_NEW_TOKEN
POLL_SECONDS=300
ALERT_THRESHOLD=7
DEDUPE_WINDOW_MINUTES=240
TIMEZONE=Asia/Singapore
STATE_FILE=/opt/oil-telegram-bot/data/state.json
```

If you want your custom feed list, also set `RSS_FEEDS`.

Important: rotate the Telegram token before deployment if it was ever shared or pasted into chat.

## 7. Test the bot manually once

```bash
cd /opt/oil-telegram-bot
source .venv/bin/activate
python bot.py
```

If it starts correctly, stop it with `Ctrl+C`.

## 8. Install the systemd service

Copy the provided service file:

```bash
sudo cp deploy/oil-telegram-bot.service /etc/systemd/system/oil-telegram-bot.service
```

If your EC2 username is not `ubuntu`, edit the service file first:

```bash
sudo nano /etc/systemd/system/oil-telegram-bot.service
```

Then start and enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now oil-telegram-bot
sudo systemctl status oil-telegram-bot
```

## 9. View logs

```bash
journalctl -u oil-telegram-bot -f
```

## 10. Update later

```bash
cd /opt/oil-telegram-bot
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart oil-telegram-bot
```

## Notes

- Run only one copy of the bot with the same Telegram token. Two copies will cause Telegram polling conflicts.
- The bot stores subscriptions and de-duplication state in `STATE_FILE`, so keep that path on disk and do not point it to `/tmp`.
