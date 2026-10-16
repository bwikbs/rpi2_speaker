#!/bin/sh
# Install on a clean Raspberry Pi OS: deps + systemd unit that starts at boot.
# Usage: git clone https://github.com/bwikbs/rpi2_speaker && cd rpi2_speaker && ./install.sh
set -eu
DIR=$(cd "$(dirname "$0")" && pwd)
USER_NAME=${SUDO_USER:-$(id -un)}
MUSIC_DIR=${MUSIC_DIR:-/mnt/music}
PORT=${PORT:-8080}

sudo apt-get update
sudo apt-get install -y --no-install-recommends mpv ffmpeg python3 python3-pip
# distro yt-dlp goes stale fast and YouTube breaks it; always take the latest from pip
sudo pip3 install -U yt-dlp --break-system-packages
sudo mkdir -p "$MUSIC_DIR"

sudo tee /etc/systemd/system/rpi2-speaker.service >/dev/null <<UNIT
[Unit]
Description=rpi2 network speaker
After=network-online.target sound.target
Wants=network-online.target

[Service]
User=$USER_NAME
Environment=MUSIC_DIR=$MUSIC_DIR
Environment=PORT=$PORT
ExecStart=/usr/bin/python3 $DIR/speaker.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now rpi2-speaker
sleep 2
sudo systemctl --no-pager status rpi2-speaker | head -5
echo "open http://$(hostname -I | cut -d' ' -f1):$PORT"
