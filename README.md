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
most widely carried stories are listed first. GDELT often rate-limits GitHub's shared runners, so when it answers
with nothing the same query goes to Google News RSS instead (the source is shown on the page and stored with the history).

- The page shows them as **In the news** (`docs/data/news-<key>.json`). The daily workflow fetches them, and the
  nowcast workflow refreshes them during the NSE session.
- Each daily run appends one row (articles, distinct headlines, outlets, headline tone) to `news/<key>.json` on the
  `scoreboard` branch.

### News tone as a forecast input (`scripts/newsfeat.py`)

- **No lookahead.** For session D the tone comes only from headlines published in the 36 hours before the *previous*
  session's close. Anything later could already describe D (live blogs get retitled with the day's result).
- **History.** One row per session in `news-daily/<key>.json` on the `scoreboard` branch. **Actions → News history
  backfill → Run workflow** fills about a year from Google News date searches (resumable). After that, every forecast
  run adds the sessions it needs.
- **Tested before trusted.** Each session's return is predicted from the tone using only earlier sessions
  (walk-forward). The tone's effect is scaled by how much it actually helped in that test, between 0 (no help, no
  effect) and 1. It has no effect at all until 60 sessions have been tested. The result shifts the best estimate,
  and the news card on the page shows the tone, the test result and the shift.
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

**Actions → Model experiments → Run workflow** backtests LightGBM variants side by side
(`scripts/experiment.py`): every variant is retrained walk-forward and scored on the same test days (by default every
second day of the last 750 trading days). A variant counts as better only if the paired t-statistic of its miss
against the current model is below about −2; anything closer is indistinguishable from luck.

Result on 13 Oct 2026 (375 test days, Sep/Oct 2023 – Oct 2026):

| | Current miss | "No change" miss | Direction right / always-up | Beats "no change"? | Variant clearly better? |
|---|---|---|---|---|---|
| NIFTY | 0.599% | 0.622% | 61.1% / 56.3% | yes (t = −2.1) | no |
| Gold | 1.006% | 1.000% | 52.0% / 56.3% | no | no |
| Silver | 1.835% | 1.860% | 54.7% / 55.5% | not clearly (t = −1.5) | no |
| Crude | 1.860% | 1.838% | 50.7% / 51.5% | no, worse (t = +2.1) | no (fewer trees beat current, not "no change") |

Variants tested: no overnight/global features, recency-weighted training (3-year half-life), last 10 years only, more
trees, fewer trees. The overnight features help NIFTY (removing them is worse); nothing else changed the picture, so
the model was left as it is. The best estimate already leans on "no change" for the commodities.


Run **Actions → Predict next candles → Run workflow** with `keys` (for example `nifty`) to run a subset without
deploying. `kronos_t` (sampling temperature, default 0.6) lets you A/B test Kronos settings; compare the backtest lines in the
job logs.

Educational project, not financial advice.
