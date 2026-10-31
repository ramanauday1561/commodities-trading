# Commodities & NIFTY forecasts

A static site (GitHub Pages, `docs/`) with forecasts for NIFTY 50, gold, silver and WTI crude, a NIFTY trade status
for the day, a live intraday chart and an honest record of how every call did. GitHub Actions does all the work; there
is no server. Educational project, not financial advice.

## Pages

| Page | What it shows |
|---|---|
| Home (`index.html`) | Next-days forecasts per market, today's NIFTY call, news, the backtest behind each number |
| Status (`status.html`) | CALL, PUT, STAY, SELL or NOTHING for NIFTY right now (only the tested 09:15 signal trades) |
| Live (`live.html`) | Today in 10-minute candles: our model and the AI's predicted close vs the real price, the track record |
| Next 10 min (`next.html`) | The model's lean for each next candle, scored as the day goes (information, not a signal) |
| History (`history.html`) | Every day's calls and trades, right or wrong |

A sidebar (`nav.js`) links them; a service worker (`sw.js`) lets the home-screen app open offline.

## What runs when

| Workflow | When | Main scripts |
|---|---|---|
| `predict.yml` | 08:30, 15:45 and 04:00 IST on weekdays, and on merges that change `scripts/` or `index.html` | `predict.py` (Kronos + LightGBM forecasts, `gbm.py`, `exo.py`, `blend.py`), `todaycall.py`, `scoreboard.py`, `news.py`, `newsfeat.py`, `daylike.py`, `nextcandle.py` |
| `intraday.yml` | Every 10 minutes in the NSE session (started by `keeper.yml`) | `todaycall.py`, `intraday.py`, `hourly.py`, `status.py` (phone alerts), `live.py`, `gift_record.py` |
| `keeper.yml` | Before the open, through the session | `keeper.py`: starts the intraday runs on time, watches the stop |
| `replay.yml` | By hand, after the close | `replay.py`: a finished day replayed as if live, with the AI |
| `status-alert-test.yml` | By hand | Sends a test alert through every configured channel |
| `experiment.yml` | By hand | `experiment.py`: backtests and the kept studies (below) |
| `tests.yml` | Every PR and push to main | `tests/` |

Helpers: `calendars.py` (exchange holidays), `rolls.py` (futures roll adjustment), `results_calendar.py` and
`us_events.py` (days the 09:15 signal stands aside), `intraday_data.py` and `overnight_data.py` (stored history),
`daymoney.py` (the ₹2 lakh box), `grok.py` (AI notes), `dailyfill.py`, `evalutil.py`, `build_manifest.py`,
`prune_data.py`, `store.sh`, `option_data.py` and `option_record.py` (real NIFTY option prices, nightly), `weekly.py` (the Saturday summary). Markets are listed in `scripts/instruments.json`.

## Where data lives

The workflows write to branches; do not delete them.

| Branch | Contents |
|---|---|
| `site-data` | The latest data files the pages read |
| `scoreboard` | Every forecast and call with its result, the daily journals, live days, GIFT Nifty recordings |
| `intraday-data` | NIFTY, Bank NIFTY and India VIX 5-minute candles since 2015 |
| `overnight-es`, `-nq`, `-nikkei`, `-hangseng`, `-india*` | Hourly overnight markets (Dukascopy) for the long backtests |

Secrets (GitHub → Settings → Secrets, never in the repo): `FRED_API_KEY`, `XAI_API_KEY` (an xAI or Groq key),
`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` and/or `NTFY_TOPIC` for alerts. The page's Rerun and Recheck buttons need a
fine-grained token with only **Actions: Read and write** on this repository; the page keeps it in that browser only.

## Changing a call: test first

Every change is backtested on history only (walk-forward), against a pass rule written down before the run, and goes
in its own PR. **Actions → Model experiments → Run workflow** with a `mode`:

- `variants` (default), `risk`, `events`, `resultsrisk`, `dailyfill`, `commodity`: the forecast models.
- `longsignal`, `history`, `preopen`, `open`, `vix`, `accuracy`, `improve`, `extreme`, `strategy`, `intrarules`,
  `nextcandle`: the NIFTY studies kept for re-testing.
- `intradata` / `dukafetch`: update the stored 5-minute / hourly overnight history.

[STUDIES.md](STUDIES.md) lists what each study found, including the finished one-off studies whose scripts were
removed. In short: the 09:15 signal made money in 2015-2021 and is about break-even since 2022 (GIFT Nifty now prices
the overnight markets into the open), and no intraday rule has covered option costs on 11 years of 5-minute candles.
