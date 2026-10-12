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
| `scripts/news.py` | **News** from [NewsMCP](https://github.com/pranciskus/newsmcp): related headlines per instrument, plus a daily news-signal history (see below) |
| `scripts/intraday.py` | **Nowcast** (NIFTY): predicts today's close from the 15-minute candles so far |
| `.github/workflows/predict.yml` | Scheduled forecasts (with backup slots + a duplicate gate) and Pages deploy |
| `.github/workflows/intraday.yml` | Four nowcasts during the NSE session, republishing the site |
| `docs/` | The site (no build step) |

Persistence uses two branches written by the workflows: `scoreboard` (small JSON records, normal commits) and
`site-data` (latest generated data, a single squashed commit). Do not delete them.

## Instruments

`scripts/instruments.json` lists them (ticker, exchange time zone and close, extra context tickers, news filters).
Add or remove an entry there; the workflow, page and scoreboard pick it up, and files of removed instruments are
dropped on the next deploy.

## News (NewsMCP)

NewsMCP clusters articles from hundreds of sources into events and ranks them by impact. Its MCP server is a thin
wrapper over a free REST API (`https://newsmcp.io/v1`, no key), so the pipeline calls the REST API directly:

- `scripts/news.py` fetches the last 36 hours per instrument (topics/regions/keywords from `news` in
  `instruments.json`) and writes `docs/data/news-<key>.json`, shown on the page as **In the news**. It runs in the
  daily workflow and refreshes during the NSE session with the nowcast.
- Each daily run also appends one row (related events, sources, top impact, headline tone) to `news/<key>.json` on
  the `scoreboard` branch.
- News is **not** a model input. NewsMCP has no archive, so it cannot be backtested on the past; once a few hundred
  days have been recorded, the history can be tested as a LightGBM feature like everything else.

To let an AI coding agent (Claude Code, Cursor, …) search the news while working on this repository, add the MCP
server to the project, e.g. `claude mcp add --scope project newsmcp -- npx -y @newsmcp/server`, which writes:

```json
{ "mcpServers": { "newsmcp": { "command": "npx", "args": ["-y", "@newsmcp/server"] } } }
```

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
