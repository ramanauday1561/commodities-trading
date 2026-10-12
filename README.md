# Commodities & NIFTY forecasts

A static site (GitHub Pages) that forecasts the next 4 trading days for NIFTY 50, gold, silver and WTI crude oil, explains the
result in plain language and keeps an honest record of how the forecasts actually did.

## How it works

| Piece | What it does |
|---|---|
| `scripts/predict.py` | Per instrument: complete Yahoo history → Kronos-base, Kronos-mini and LightGBM forecasts → walk-forward backtests → **Best estimate** (backtest-weighted blend, shrunk toward "no change") with calibrated ranges and probabilities |
| `scripts/gbm.py`, `scripts/exo.py` | LightGBM on the full history plus overnight/global context (US indices, VIX, India VIX, USD/INR, oil, gold, dollar, Asia) |
| `scripts/blend.py` | Non-negative least-squares stacking, cross-validated; Platt scaling for probabilities |
| `scripts/scoreboard.py` | **Live scoreboard**: saves every forecast, scores it once the real close is known |
| `scripts/news.py` | **News**: related headlines per instrument from GDELT, plus a daily news-signal history (see below) |
| `scripts/intraday.py` | **Nowcast** (NIFTY): predicts today's close from the 15-minute candles so far |
| `.github/workflows/predict.yml` | Scheduled forecasts (with backup slots + a duplicate gate) and Pages deploy |
| `.github/workflows/intraday.yml` | Four nowcasts during the NSE session, republishing the site |
| `docs/` | The site (no build step) |

Persistence uses two branches written by the workflows: `scoreboard` (small JSON records, normal commits) and
`site-data` (latest generated data, a single squashed commit). Do not delete them.

## Instruments

`scripts/instruments.json` lists them (ticker, exchange time zone and close, extra context tickers, news query).
Add or remove an entry there; the workflow, page and scoreboard pick it up, and files of removed instruments are
dropped on the next deploy.

## News

`scripts/news.py` fetches related headlines from the last 36 hours per instrument from the free
[GDELT DOC 2.0 API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) (no key; one search query per instrument,
set in `news.query` in `instruments.json`). Copies of the same headline from different outlets are grouped, and the
most widely carried stories are listed first.

- The page shows them as **In the news** (`docs/data/news-<key>.json`). The daily workflow fetches them, and the
  nowcast workflow refreshes them during the NSE session.
- Each daily run appends one row (articles, distinct headlines, outlets, headline tone) to `news/<key>.json` on the
  `scoreboard` branch.
- News is **not** a model input. Once a few hundred days are recorded, the history can be tested as a LightGBM feature
  the same way every other input was.
- If the API is slow or down, the step gives up within two minutes and the page keeps the previous headlines.

[NewsMCP](https://github.com/pranciskus/newsmcp) was the first choice, but the service was shut down in October 2026
(its API answers every request with HTTP 410), so its MCP server no longer works either.

## Reliable scheduling

GitHub's `schedule` trigger is best-effort: runs are often late and sometimes skipped. Each slot therefore has backup
cron entries, and a `gate` job skips a run if another run on `main` finished or started in the last 90 minutes.

For stricter timing, call the workflow from an external scheduler (for example cron-job.org). Create a fine-grained
personal access token limited to this repository with **Actions: Read and write**, then schedule an HTTP request:

```
POST https://api.github.com/repos/<owner>/<repo>/actions/workflows/predict.yml/dispatches
Authorization: Bearer <token>
Accept: application/vnd.github+json
Content-Type: application/json

{"ref": "main"}
```

Use the same pattern with `intraday.yml` for the nowcast. Suggested times (IST): 08:30 pre-market, 15:45 after the
close, 04:00 after the US futures close; nowcast at 10:00, 11:30, 13:00, 14:30.

## Experiments

Run **Actions → Predict next candles → Run workflow** with `keys` (for example `nifty`) to run a subset without
deploying. `kronos_t` (sampling temperature, default 0.6) lets you A/B test Kronos settings; compare the backtest lines in the
job logs.

Educational project, not financial advice.
