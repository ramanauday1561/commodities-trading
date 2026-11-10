#!/usr/bin/env bash
# Sets up the order server (orders_server.py) on a fresh Ubuntu (24.04 or newer) box with a fixed public IP: the
# Hostinger VPS in Mumbai since 10 Nov 2026. Run it once, as root, in hPanel's Browser terminal for the VPS:
#   curl -fsSL https://raw.githubusercontent.com/ramanauday1561/commodities-trading/main/server/setup.sh -o setup.sh
#   bash setup.sh
# It asks for the Kite API key and secret (typed, not shown, not saved in the shell history), makes a long passcode
# for the phone, and prints the server's address and the passcode once. Run it again later to update the code; the
# settings are kept (delete /etc/nifty-orders.env first to change them).
set -euo pipefail

REPO=https://github.com/ramanauday1561/commodities-trading.git
APP=/opt/nifty-orders
ENV=/etc/nifty-orders.env

sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-cryptography git caddy >/dev/null

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

sudo tee /etc/systemd/system/nifty-orders.service >/dev/null <<EOF
[Unit]
Description=NIFTY order server for your own picks
After=network-online.target
Wants=network-online.target

[Service]
User=orders
EnvironmentFile=$ENV
Environment=ORDERS_DATA=/var/lib/nifty-orders
ExecStart=/usr/bin/python3 $APP/server/orders_server.py
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

sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$HOST {
  reverse_proxy 127.0.0.1:8787
}
EOF

sudo timedatectl set-timezone Asia/Kolkata
sudo systemctl daemon-reload
sudo systemctl enable -q --now nifty-orders
sudo systemctl restart nifty-orders caddy

echo
echo "Done. Server address for the Orders page:  https://$HOST"
echo "Static IP to whitelist in the Kite developer console:  $IP"
if [ "${NEW:-}" = 1 ]; then
  echo "Passcode for the Orders page (shown once; it is also in $ENV, readable only by root):"
  echo "  $(sudo grep ^ORDERS_PASSCODE= "$ENV" | cut -d= -f2-)"
fi
echo "Logs: sudo journalctl -u nifty-orders -f"
