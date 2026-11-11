# Order server (your own picks, real money)

Since 1 April 2026, Zerodha accepts orders through the Kite Connect API only from a **static IP** whitelisted in the
Kite developer console. Market data needs no static IP. So the app stays as it is:

- the website on GitHub Pages;
- the data runs on GitHub Actions.

Only placing orders moves to a small server with a static IP. That server runs `orders_server.py`.

From the **Orders** page on your phone you enter your pick:

- the option;
- the lots;
- the entry: now, or at a price;
- a stop-loss price;
- a target (optional);
- a time to be out by.

The server then runs the pick by itself:

1. It buys with a limit order, never a market order.
2. As soon as the buy fills, it puts your stop-loss order at the exchange.
3. It sells at your target or at your exit time.

Limits set on the server (not from the phone):

- most lots a pick;
- most picks open at once;
- most loss in a day.

When the day's loss limit is reached, the server sells everything and takes no more picks that day. **Stop everything**
on the phone does the same at once. The server only buys NIFTY options, intraday (MIS).

## One-time setup (about 20 minutes)

### 1. The server (Hostinger VPS)

The server is a **Hostinger KVM 1 VPS in Mumbai** (bought 10 Nov 2026, Ubuntu 26.04 LTS, plain OS, no Docker manager,
no malware scanner). For a new one: hpanel.hostinger.com → VPS → the smallest plan, location **India (Mumbai)**,
OS **Plain OS → Ubuntu** (24.04 or newer).

1. **The IP to whitelist** is the VPS's IPv4, shown on its Overview page in hPanel. It stays the same while you keep
   the VPS in the same location. **Moving it to another data centre changes the IP**, and Kite allows one change a
   week, so leave it in Mumbai.
2. **Firewall** (hPanel → the VPS → **Security → Firewall**): create one, add **accept** rules for **SSH (22)**,
   **HTTP (80)** and **HTTPS (443)** from any source, then activate it on the VPS. Hostinger's firewall drops
   everything not allowed, so add all three before activating. Caddy uses port 80 to get the HTTPS certificate.
3. **Cost:** check the renewal price before the term ends; renewing at a sale price is much cheaper.

### 2. Install

In hPanel, open the VPS and tap **Browser terminal** (you are logged in as root), then run:

```
curl -fsSL https://raw.githubusercontent.com/ramanauday1561/commodities-trading/main/server/setup.sh -o setup.sh
bash setup.sh
```

It asks for:

- the Kite API key and secret, typed without being shown;
- your limits.

It then prints three things:

- the **server address** (`https://<ip>.sslip.io`);
- the **static IP**;
- the **passcode**, shown once.

Keep the passcode private. It is like a password for placing orders.

### 3. Whitelist the IP in Kite

1. Go to developers.kite.trade, open your app, and find **IP Whitelist**.
2. Add the static IP as the primary IP.
3. Accept the self-use declaration. The exchange allows one change a week.

### 4. Connect the phone

1. Open **Orders** on the site (⋯ menu).
2. Enter the server address and the passcode. They are saved in that browser only.

## Charges and the Money page (11 Nov 2026)

- **Before you buy:** the Orders page asks Kite for the exact charges of a round trip (brokerage, STT, exchange and
  SEBI fees, stamp duty, GST) and shows them with the points the option must rise just to cover them. The REAL ORDER
  confirmation repeats it.
- **P&L after charges:** a closed pick's P&L takes off Kite's charges for its real fills; an open pick's takes off
  the estimate made when it was placed. The daily loss limit counts charges too. If Kite's charges API does not
  answer, about Rs120 a lot is used and marked as an estimate.
- **Money** (⋯ menu → Money): only the account's money, from Kite: today's result after charges, how it adds up
  (started with, trades, charges, now, free to trade), and every trading day since. It uses the Orders page's address
  and passcode. The server keeps one line of totals a day in `money.json` (never positions).
- **To get these on the server**, run `bash setup.sh` again in the Web console after the release is in `main`: it
  pulls the new code and keeps your settings.

## Automatic ★ picks (11 Nov 2026, asked by the owner)

With the switch on, the server buys every new ★ lean by itself, without the phone:

- every 75 seconds it reads the Next 10 page's leans (the `site-data` branch, through GitHub's API);
- for a ★ lean made at most about 3 minutes ago: the at-the-money option of the next expiry after today (CALL when
  it leans up, PUT when down), **1 lot**, entry now, **stop 10% under** the price, **out after 30 minutes**;
- each lean is tried **once** (also when Kite or a limit refuses it), and every pick goes through the same checks as a
  phone pick: the lots, open-pick and daily-loss limits, the Kite login, 09:15-15:00.

Turn it **on** (Web console, after `bash setup.sh` has the new code):
```
echo AUTO_STAR=1 >> /etc/nifty-orders.env && systemctl restart nifty-orders
```
**Practice mode** (no real orders): the same picks, bought and sold on paper at Kite's live prices (the ask in, the
stop or the bid at the exit time out, Kite's charges), shown on the Orders page as "practice" and never counted in the
real P&L or the daily loss limit. Use it while F&O is not active, or to check the whole path on a new day:
```
sed -i 's/^AUTO_STAR=.*/AUTO_STAR=practice/' /etc/nifty-orders.env && systemctl restart nifty-orders
```
**Leans made on the server** (11 Nov 2026): with the switch on (or practice), the server also makes the Next 10 lean
itself, 15 seconds after each 10-minute candle, from Kite's 5-minute candles and the same model (downloaded from
`site-data` each morning). It no longer waits for GitHub's run (sometimes minutes late). `setup.sh` installs numpy,
pandas and lightgbm for it; if that fails, or with `AUTO_LOCAL=0`, only GitHub's leans are used. The log shows
`local lean 10:05 down (star)` for each one.

Turn it **off**:
```
sed -i 's/^AUTO_STAR=.*/AUTO_STAR=0/' /etc/nifty-orders.env && systemctl restart nifty-orders
```
**Stop everything** on the Orders page also stops it for the rest of the day. The Orders page shows "Automatic ★ picks:
ON" and marks each automatic pick. The ★ leans lost ₹53-72 a lot a trade in every backtest; this trades them anyway,
at the owner's request.

## Every day

1. Log in to Kite on the **Kite login** page before trading, as now. The server picks up the day's token within a
   minute.
2. Place picks between 09:15 and 15:00. Every pick must be out by 15:15. Zerodha also squares off MIS positions at
   about 15:20.

## Good to know

- **Where the picks are kept.** Picks, orders and P&L stay on the server's disk and your phone. They never go to this
  repository, and the server's log does not print them.
  - Logs: `sudo journalctl -u nifty-orders -f`
- **Updating.** To update the code, run `bash setup.sh` again; your settings are kept. To change the limits, edit
  `/etc/nifty-orders.env` with `sudo nano`, then run `sudo systemctl restart nifty-orders`.
- **If the server goes down.** The stop-loss is already at the exchange. A target or an exit time is not, so check
  Kite if the server is unreachable.
- **Gaps.** A stop-loss is a stop-limit order. In a fast fall it can trigger and not fill at once; the server
  re-prices it under the bid after 10 seconds. The loss can be more than entry minus stop.
- **Rules.** A personal static IP serves you and your immediate family. Automating more than 10 orders a second needs
  exchange registration; this server sends a few orders a minute.
- **Money.** None of the app's own ideas (leans, the 09:15 signal, the straddle) has passed its backtest. This server
  only runs picks you choose.
