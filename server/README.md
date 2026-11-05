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

### 1. Create the server

In the AWS Lightsail console:

1. Create an instance:
   - Region: **Mumbai (ap-south-1)**
   - Platform: Linux
   - Blueprint: OS only, **Ubuntu 24.04**
   - Plan: the smallest is enough, about US$5 a month.
2. In **Networking**, create a **static IP** and attach it to the instance. A static IP is free while it is attached.
   If you detach it or stop the instance, it is charged.
3. In the instance's **Networking** tab, IPv4 firewall, add a rule for **HTTPS (TCP 443)**. SSH (22) and HTTP (80) are
   already open; Caddy uses port 80 to get the HTTPS certificate.

### 2. Install

Open the instance's browser SSH window (**Connect using SSH**) and run:

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
