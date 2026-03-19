#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/oil-telegram-bot"
SERVICE_NAME="oil-telegram-bot"

sudo dnf update -y
sudo dnf install -y python3 python3-pip git

sudo mkdir -p "$APP_DIR"
sudo chown -R ec2-user:ec2-user "$APP_DIR"

cd "$APP_DIR"

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

mkdir -p "$APP_DIR/data"

if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "Created $APP_DIR/.env from .env.example. Edit it before starting the service."
fi

sudo cp "$APP_DIR/deploy/oil-telegram-bot.service" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload

echo
echo "Bootstrap complete."
echo "Next steps:"
echo "1. Edit $APP_DIR/.env and add your Telegram bot token."
echo "2. Start the service with: sudo systemctl enable --now ${SERVICE_NAME}"
echo "3. Tail logs with: journalctl -u ${SERVICE_NAME} -f"
