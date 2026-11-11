#!/usr/bin/env bash
# Sets up the order server (orders_server.py) on a fresh Ubuntu (24.04 or newer) box with a fixed public IP: the
# Hostinger VPS in Mumbai since 10 Nov 2026. Run it once, as root, in hPanel's Web console for the VPS:
#   curl -fsSL https://raw.githubusercontent.com/ramanauday1561/commodities-trading/main/server/setup.sh -o setup.sh
#   bash setup.sh
# It asks for the Kite API key and secret (typed, not shown, not saved in the shell history), makes a long passcode
# for the phone, and prints the server's address and the passcode once. To update later run the copy in the code,
# bash /opt/nifty-orders/server/setup.sh (the first day's ~/setup.sh is an old copy of these steps); the
# settings are kept (delete /etc/nifty-orders.env first to change them).
set -euo pipefail

REPO=https://github.com/ramanauday1561/commodities-trading.git
APP=/opt/nifty-orders
ENV=/etc/nifty-orders.env

sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-cryptography python3-venv libgomp1 git caddy jq >/dev/null

if [ -d "$APP/.git" ]; then sudo git -C "$APP" pull -q --ff-only; else sudo git clone -q --depth 1 "$REPO" "$APP"; fi
id orders >/dev/null 2>&1 || sudo useradd --system --home /var/lib/nifty-orders --create-home --shell /usr/sbin/nologin orders
sudo chmod 700 /var/lib/nifty-orders

IP=$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')   # the IP orders leave from: the one Kite must whitelist
HOST="${IP//./-}.sslip.io"                      # a free name for the IP, so Caddy can get a real HTTPS certificate

if ! sudo test -f "$ENV"; then
  read -rsp "Kite API key: " KEY; echo
  read -rsp "Kite API secret: " SECRET; echo
  read -rp "Most lots in one pick [1]: " LOTS; LOTS=${LOTS:-1}
  read -rp "Most picks open at once [2]: " OPEN; OPEN=${OPEN:-2}
  read -rp "Most rupees to lose in a day before everything is sold [3000]: " LOSS; LOSS=${LOSS:-3000}
  CODE=$(python3 -c 'import secrets; print(secrets.token_urlsafe(30))')
  sudo install -m 600 -o root -g root /dev/null "$ENV"
  printf 'KITE_API_KEY=%s\nKITE_API_SECRET=%s\nORDERS_PASSCODE=%s\nMAX_LOTS=%s\nMAX_OPEN=%s\nMAX_LOSS_DAY=%s\nALLOW_ORIGIN=https://ramanauday1561.github.io\n' \
    "$KEY" "$SECRET" "$CODE" "$LOTS" "$OPEN" "$LOSS" | sudo tee "$ENV" >/dev/null
  unset KEY SECRET
  NEW=1
fi

# 11 Nov 2026: the 10-minute market updates can run here instead of on GitHub (server/market_run.sh). Their keys go in
# a second file, asked once: a GitHub token (fine-grained, this repository only, Contents: Read and write) to save the
# data, and the phone-alert and AI keys GitHub's jobs use. Typed, not shown, readable only by root.
MENV=/etc/nifty-market.env
if ! sudo test -f "$MENV"; then
  read -rp "Run the 10-minute market updates on this server too? [y/N]: " YN
  if [ "${YN,,}" = "y" ]; then
    read -rsp "GitHub token (Contents: Read and write on commodities-trading): " GHT; echo
    read -rsp "Telegram bot token (Enter to skip): " TGT; echo
    read -rsp "Telegram chat id (Enter to skip): " TGC; echo
    read -rsp "xAI API key for the AI notes (Enter to skip): " XAI; echo
    read -rsp "FRED API key (Enter to skip): " FRED; echo
    read -rsp "ntfy topic (Enter to skip): " NTFY; echo
    sudo install -m 600 -o root -g root /dev/null "$MENV"
    printf 'GH_TOKEN=%s\nTELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\nXAI_API_KEY=%s\nFRED_API_KEY=%s\nNTFY_TOPIC=%s\n' \
      "$GHT" "$TGT" "$TGC" "$XAI" "$FRED" "$NTFY" | sudo tee "$MENV" >/dev/null
    unset GHT TGT TGC XAI FRED NTFY
  fi
fi

# 11 Nov 2026: the server also makes the Next 10 lean itself (LocalLeans), which needs numpy, pandas and lightgbm;
# they go in a private Python environment. If that fails the server still runs, on GitHub's leans only.
PY=/usr/bin/python3
if sudo python3 -m venv --system-site-packages "$APP/venv" >/dev/null 2>&1 && \
   sudo "$APP/venv/bin/pip" install -q --upgrade numpy pandas lightgbm yfinance exchange_calendars requests >/dev/null 2>&1; then
  PY="$APP/venv/bin/python"
else
  echo "note: numpy / pandas / lightgbm not installed; the server will use GitHub's leans only"
fi
sudo install -d -m 755 -o orders -g orders /var/lib/nifty-public        # the page files Caddy serves at /data/

sudo tee /etc/systemd/system/nifty-orders.service >/dev/null <<EOF
[Unit]
Description=NIFTY order server for your own picks
After=network-online.target
Wants=network-online.target

[Service]
User=orders
EnvironmentFile=$ENV
EnvironmentFile=-$MENV
Environment=ORDERS_DATA=/var/lib/nifty-orders
ExecStart=$PY $APP/server/orders_server.py
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/nifty-orders
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/nifty-market.service >/dev/null <<EOF
[Unit]
Description=NIFTY 10-minute market update (server/market_run.sh)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=orders
EnvironmentFile=$ENV
EnvironmentFile=-$MENV
Environment=ORDERS_DATA=/var/lib/nifty-orders APP=$APP
ExecStart=/bin/bash $APP/server/market_run.sh
TimeoutStartSec=540
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/nifty-orders /var/lib/nifty-public
ProtectHome=true
PrivateTmp=true
EOF

sudo tee /etc/systemd/system/nifty-market.timer >/dev/null <<EOF
[Unit]
Description=NIFTY market updates: 08:57 and every 10 minutes 09:05-15:55 IST on weekdays (the script skips the rest)

[Timer]
OnCalendar=Mon..Fri 08:57:10
OnCalendar=Mon..Fri 09..15:05/10:10
AccuracySec=1s

[Install]
WantedBy=timers.target
EOF

sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$HOST {
  handle_path /data/* {
    root * /var/lib/nifty-public
    header Access-Control-Allow-Origin "*"
    header Cache-Control "no-store"
    file_server
  }
  handle {
    reverse_proxy 127.0.0.1:8787
  }
}
EOF

# 11 Nov 2026: the VPS also has an IPv6 address, and orders went out from it; Kite only knows the whitelisted IPv4
# address and refused them ("IP 2a02:... is not allowed"). Prefer IPv4 for every connection from this box.
grep -q '^precedence ::ffff:0:0/96' /etc/gai.conf 2>/dev/null || echo 'precedence ::ffff:0:0/96  100' | sudo tee -a /etc/gai.conf >/dev/null
sudo timedatectl set-timezone Asia/Kolkata
sudo systemctl daemon-reload
sudo systemctl enable -q --now nifty-orders
sudo systemctl restart nifty-orders caddy
if sudo grep -q '^GH_TOKEN=.\+' "$MENV" 2>/dev/null; then
  sudo systemctl enable -q --now nifty-market.timer
  echo "Market updates run here: next $(systemctl show nifty-market.timer -p NextElapseUSecRealtime --value)"
else
  sudo systemctl disable -q --now nifty-market.timer 2>/dev/null || true
  echo "Market updates stay on GitHub (no GitHub token in $MENV)."
fi

echo
echo "Done. Server address for the Orders page:  https://$HOST"
echo "Static IP to whitelist in the Kite developer console:  $IP"
if [ "${NEW:-}" = 1 ]; then
  echo "Passcode for the Orders page (shown once; it is also in $ENV, readable only by root):"
  echo "  $(sudo grep ^ORDERS_PASSCODE= "$ENV" | cut -d= -f2-)"
fi
echo "Logs: sudo journalctl -u nifty-orders -f   (market updates: sudo journalctl -u nifty-market -n 40)"
echo "To update later: bash $APP/server/setup.sh"
