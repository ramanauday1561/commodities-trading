#!/usr/bin/env bash
# One 10-minute market update on the VPS (11 Nov 2026, asked by the owner): the same steps as GitHub's "Intraday
# nowcast" job (.github/workflows/intraday.yml), run by the nifty-market timer 10 seconds after each 10-minute candle
# (08:57, then 09:25 ... 15:25 IST on NSE trading days) instead of waiting for GitHub (its runs start late or queue).
#   - It writes the same files to the same data branches (site-data, scoreboard, options-live), so the pages and
#     GitHub's other jobs see no difference, plus runner.json: {"by": "vps", "at": ...}. While that is fresh GitHub's
#     keeper and fallback timer leave the runs to the VPS; if the VPS goes quiet for 15 minutes they take over.
#   - It copies the page files to /var/lib/nifty-public, which Caddy serves at https://<this box>/data/ for the pages
#     to read within seconds of each run (docs/fresh.js).
# Not done here: publishing the website (GitHub Pages; the pages read data from site-data or this box), the 15:50
# post-close forecast and the training (GitHub's predict.yml), position alerts and the stop watcher (keeper.yml).
# Keys: the Kite key and secret from /etc/nifty-orders.env; GH_TOKEN (contents read/write on this repo), the
# Telegram, xAI, FRED and ntfy keys from /etc/nifty-market.env, typed in by the owner in setup.sh. None is printed.
set -uo pipefail
APP=${APP:-/opt/nifty-orders}
DATA=${ORDERS_DATA:-/var/lib/nifty-orders}
W=$DATA/market
PUBLIC=${MARKET_PUBLIC:-/var/lib/nifty-public}
PY=/usr/bin/python3; [ -x "$APP/venv/bin/python" ] && PY="$APP/venv/bin/python"
export HOME=$DATA PYTHONPATH="$APP/scripts" KITE_DIR="$DATA/kite" DATA_HEALTH="$W/docs/data/data-health.json"
export GITHUB_REPOSITORY=ramanauday1561/commodities-trading GITHUB_REF=refs/heads/main

mkdir -p "$W/docs/data" "$PUBLIC" && cd "$W" || exit 1
ln -sfn "$APP/scripts" scripts

# only on NSE trading days, at the update times (the timer also fires at 09:05, 09:15 and after 15:25);
# MARKET_FORCE=1 runs it now (a test run by hand)
[ -n "${MARKET_FORCE:-}" ] || "$PY" - <<'EOF' || exit 0
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from calendars import is_session
now = datetime.now(ZoneInfo("Asia/Kolkata"))
m = now.hour * 60 + now.minute
ok = is_session(now.date(), "XBOM") and (m in (8 * 60 + 57, 8 * 60 + 58) or 9 * 60 + 25 <= m <= 15 * 60 + 27)
print(f"market run {now:%H:%M:%S}: {'go' if ok else 'not an update time'}", flush=True)
sys.exit(0 if ok else 1)
EOF

exec 9>"$DATA/market.lock"
flock -n 9 || { echo "the previous run is still going; skipped"; exit 0; }
[ -n "${GH_TOKEN:-}" ] || { echo "no GH_TOKEN in /etc/nifty-market.env: GitHub keeps running the updates"; exit 0; }

step() { echo "-- $1"; }
step "latest published data"
bash scripts/store.sh pull site-data docs/data >/dev/null

step "nowcast"
"$PY" -u scripts/intraday.py nifty >/dev/null || echo "nowcast failed"

step "today's call"
bash scripts/store.sh pull scoreboard store >/dev/null
timeout 480 "$PY" -u scripts/todaycall.py store docs/data >/dev/null || echo "today's call failed"
timeout 120 "$PY" -u scripts/gift_record.py store docs/data >/dev/null || true
bash scripts/store.sh push scoreboard store >/dev/null || echo "scoreboard push failed"

step "status page, phone alerts, live chart, leans"
bash scripts/store.sh pull scoreboard store >/dev/null
"$PY" -u scripts/live.py docs/data store morning || true
"$PY" -u scripts/status.py docs/data store || echo "status failed"
"$PY" -u scripts/live.py docs/data store run || true
bash scripts/store.sh push scoreboard store >/dev/null || echo "scoreboard push failed"

step "live option prices"
if [ -f "$KITE_DIR/session.json" ]; then
  bash scripts/store.sh pull options-live optlive >/dev/null
  timeout 180 "$PY" -u scripts/options_live.py snap optlive docs/data || echo "option prices failed"
  bash scripts/store.sh push options-live optlive >/dev/null || echo "options-live push failed"
fi

step "hourly candles"
timeout 120 "$PY" -u scripts/hourly.py docs/data nifty >/dev/null || true

step "save to site-data and serve"
printf '{"by":"vps","at":"%s"}\n' "$(TZ=Asia/Kolkata date -Iseconds)" > docs/data/runner.json
FILES="today-nifty.json intraday-nifty.json hourly-nifty.json status.json status-today.json live-nifty.json next-nifty.json
gift-nifty.json data-health.json options-live.json runner.json"
snap=$(mktemp -d)
bash scripts/store.sh pull site-data "$snap" >/dev/null
for f in $FILES docs/data/news-*.json; do f=${f#docs/data/}; [ -f "docs/data/$f" ] && cp "docs/data/$f" "$snap/"; done
bash scripts/store.sh push site-data "$snap" >/dev/null || echo "site-data push failed"
rm -rf "$snap"
for f in docs/data/*.json; do [ -f "$f" ] && install -m 644 "$f" "$PUBLIC/"; done     # every page file, for Caddy

step "news (after the save, as on GitHub)"
timeout 240 "$PY" -u scripts/news.py docs/data "$W/news-store" >/dev/null || true
for f in docs/data/news-*.json; do [ -f "$f" ] && install -m 644 "$f" "$PUBLIC/"; done
echo "market run done $(TZ=Asia/Kolkata date +%H:%M:%S)"
