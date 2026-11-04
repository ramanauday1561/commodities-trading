# Commodities & NIFTY forecasts

A static site (GitHub Pages, `docs/`) with forecasts for NIFTY 50, gold, silver and WTI crude, a NIFTY trade status
for the day, a live intraday chart and an honest record of how every call did. GitHub Actions does all the work; there
is no server. Educational project, not financial advice.

## Pages

| Page | What it shows |
|---|---|
| Today (`today.html`) | The day on one screen: NIFTY, the signal, live option prices and the paper trade, Next 10 min, GIFT Nifty and the AI's read, the data checks |
| Home (`index.html`) | Next-days forecasts per market, today's NIFTY call, news, the backtest behind each number |
| Status (`status.html`) | CALL, PUT, STAY, SELL or NOTHING for NIFTY right now (only the tested 09:15 signal trades) |
| Live (`live.html`) | Today in 10-minute candles: our model and the AI's predicted close vs the real price, the track record |
| Next 10 min (`next.html`) | The expected size of the next 10-minute move (tested), and the model's lean for it, scored as the day goes (information, not a signal) |
| History (`history.html`) | Every day's calls and trades, right or wrong |
| Kite login (`kite.html`) | The morning Kite Connect login: Kite's own 5-minute candles in place of Yahoo's for the day |

`nav.js` links them: a Liquid Glass tab bar and a "More" menu (Glisse, MIT, on React 18; `ui/` builds
`docs/vendor/glass-ui.js` with `npm install && npm run build`, so nothing loads from a CDN), glass behind the cards and glass
buttons, on the shared background in `theme.css`. Without the module (an old browser, or `?classic` in the address) the
pages keep the classic sidebar. A service worker (`sw.js`) lets the home-screen app open offline.

## What runs when

| Workflow | When | Main scripts |
|---|---|---|
| `predict.yml` | 08:30, 15:45 and 04:00 IST on weekdays, and on merges that change `scripts/` or `index.html` | `predict.py` (Kronos + LightGBM forecasts, `gbm.py`, `exo.py`, `blend.py`), `todaycall.py`, `scoreboard.py`, `news.py`, `newsfeat.py`, `daylike.py`, `nextcandle.py` |
| `intraday.yml` | Every 10 minutes in the NSE session (started by `keeper.yml`) | `todaycall.py`, `intraday.py`, `hourly.py`, `status.py` (phone alerts), `live.py`, `gift_record.py` |
| `keeper.yml` | Before the open, through the session | `keeper.py`: starts the intraday runs on time, watches the stop, and (after the Kite login) your own NIFTY / BANKNIFTY option positions every 2 minutes: phone alerts only, via `positions.py` |
| `replay.yml` | By hand, after the close | `replay.py`: a finished day replayed as if live, with the AI |
| `status-alert-test.yml` | By hand | Sends a test alert through every configured channel |
| `kite-login.yml` | From the Kite login page, each morning | `kite.py`: trades Kite's one-time request token for the day's access token (stored encrypted) |
| `experiment.yml` | By hand | `experiment.py`: backtests and the kept studies (below) |
| `tests.yml` | Every PR and push to main | `tests/` |

Prices: `prices.py` serves NIFTY 50, Bank NIFTY and India VIX to every script, from Kite Connect after the morning
login (`kite.py`, the Kite login page) and from Yahoo otherwise or when Kite fails or falls behind; its checks (stale
candles, a missing session, Kite errors) go to `data-health.json` and the Status page. Other markets come from Yahoo.
Helpers: `calendars.py` (exchange holidays), `rolls.py` (futures roll adjustment), `results_calendar.py` and
`us_events.py` (days the 09:15 signal stands aside), `intraday_data.py` and `overnight_data.py` (stored history),
`daymoney.py` (the ₹2 lakh box), `grok.py` (AI notes), `dailyfill.py`, `evalutil.py`, `build_manifest.py`,
`prune_data.py`, `store.sh`, `option_data.py` and `option_record.py` (real NIFTY option prices, nightly), `options_live.py`
(live option prices from Kite every 10 minutes, the Live page's line), `weekly.py` (the Saturday summary). Markets are listed in `scripts/instruments.json`.

## Where data lives

The workflows write to branches; do not delete them.

| Branch | Contents |
|---|---|
| `site-data` | The latest data files the pages read |
| `kite-session` | The day's Kite access token, encrypted with a key made from the API secret, and its expiry |
| `scoreboard` | Every forecast and call with its result, the daily journals, live days, GIFT Nifty recordings |
| `options-live` | NIFTY option quotes every 10 minutes (21 strikes, two expiries, with open interest; from 5 Nov 2026), their 5-minute candles after the close, and `paper/straddle.json`: the paper straddle's every day (Kite, from 4 Nov 2026) |
| `intraday-data` | NIFTY, Bank NIFTY and India VIX 5-minute candles since 2015 (Kite's since 19 May 2026; `sources.json` says which source each day came from; the Yahoo-era copy is `intraday-data-yahoo-backup`) |
| `overnight-es`, `-nq`, `-nikkei`, `-hangseng`, `-india*` | Hourly overnight markets (Dukascopy) for the long backtests |

Secrets (GitHub → Settings → Secrets, never in the repo): `FRED_API_KEY`, `XAI_API_KEY` (an xAI or Groq key),
`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` and/or `NTFY_TOPIC` for alerts, `KITE_API_KEY` + `KITE_API_SECRET` for Kite
Connect's market data (no static IP needed: that covers order placement, which the app never does; the Kite app's
redirect URL is the site's `kite.html`). The page's Rerun and Recheck buttons need a
fine-grained token with only **Actions: Read and write** on this repository; the page keeps it in that browser only.

## Changing a call: test first

Every change is backtested on history only (walk-forward), against a pass rule written down before the run, and goes
in its own PR. **Actions → Model experiments → Run workflow** with a `mode`:

- `variants` (default), `risk`, `events`, `resultsrisk`, `dailyfill`, `commodity`: the forecast models.
- `longsignal`, `history`, `preopen`, `open`, `vix`, `accuracy`, `improve`, `extreme`, `strategy`, `intrarules`,
  `nextcandle`, `shortopt`, `movesize`: the NIFTY studies kept for re-testing.
- `intradata` / `dukafetch`: update the stored 5-minute / hourly overnight history.
- `kitecheck` / `kitecompare` / `kiterepair` / `kitepositions`: are the Kite secrets accepted; Kite vs Yahoo side by side; Kite's 5-minute
  candles in place of Yahoo's in the stored history (test_days = the first day; all need that day's login).
- `nextreplay` (test_days = a date): replay that day's Next 10 min leans with the model as it was that morning, beside what the live page showed.

[STUDIES.md](STUDIES.md) lists what each study found, including the finished one-off studies whose scripts were
removed. In short: the 09:15 signal made money in 2015-2021 and is about break-even since 2022 (GIFT Nifty now prices
the overnight markets into the open), and no intraday rule has covered option costs on 11 years of 5-minute candles.
