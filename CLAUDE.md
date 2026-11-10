# Working on this repo with Claude

Read this first, then `notes/HANDOFF.md` (the full history: what was built, tested, decided and why), `README.md`
(pages, workflows, data branches) and `STUDIES.md` (every backtest and its result).

## The project in one paragraph

A NIFTY options trading *information* app: a static site on GitHub Pages (`docs/`) that the owner installs on an iPhone
home screen, with GitHub Actions doing all the work (no server). It shows forecasts, a 09:15 signal, a live chart,
the "Next 10 minutes" lean (the screen watched all day), real Kite option prices, paper accounts and an honest record
of every call. Prices come from Zerodha Kite Connect (market data only) after a daily login, Yahoo otherwise.

## Rules the owner set (always follow)

- **Never place orders.** The app reads market data and positions only. Order placement, an order server and any AWS
  / Render hosting were built on 5 Nov 2026 and removed the same day at the owner's request (PRs #102, #104). Do not
  bring them back unless asked again.
- **Secrets live only in GitHub secrets** (`KITE_API_KEY`, `KITE_API_SECRET`, `FRED_API_KEY`, `XAI_API_KEY`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `NTFY_TOPIC`; Kaggle keys, if ever, only as `KAGGLE_USERNAME` / `KAGGLE_KEY`).
  Never ask for them in chat, never print or commit them. Request tokens and access tokens are masked in logs.
- **Positions are never printed in logs or stored** anywhere; they go to the phone only (`positions.py`, `keeper.py`).
- **Raw broker data stays out of `main`**: it lives in this repo's data branches (`options-live`, `futures-data`,
  `intraday-data`, `kite-session`, ...). No private repo.
- **Backtest before any model change**, walk-forward on history only, with the pass rule written in the script's
  docstring *before* the run. The leans and the AI notes are information only, never trade signals.
- **Do not use the 151-trading-strategies repo.**
- **Branch flow:** every change is a PR into **`dev`**; a release PR takes `dev` into `main`; `main` is what the app
  runs. The owner merges releases (they have also asked Claude to merge PRs into `dev` after CI passes; ask if unsure).
- Every change goes in its own PR. Reply to the owner in plain, short language; they read on a phone.

## Daily operations

- The owner logs in to Kite each morning on `kite.html` (token valid until 06:00 next day, stored encrypted in the
  `kite-session` branch).
- GitHub's own cron runs 2-5 hours late, so a scheduled routine **"NIFTY pre-open starter"** (08:22 IST, weekdays)
  dispatches `keeper.yml` and `predict.yml` on trading days. It fires into the *old* Claude session; in a new session,
  if the owner wants the check-ins there, update the routine to point at the new session (claude-code-remote
  `update_trigger` / `create_trigger`).
- NSE holidays come from `scripts/calendars.py` (`is_session(day, "XBOM")`); e.g. 10 Nov and 24 Nov 2026 are holidays.
- Since 3 Aug 2026 NSE has a **closing auction**: NIFTY stands still from 15:15 and the close is set at 15:30, so the
  15:15 and 15:20 5-minute bars are flat and the 15:25 bar jumps to the close. Not a data bug. The last lean is 15:05.

## Checking UI changes

Use Playwright (pre-installed Chromium) at iPhone 14 size 393x852, simulating the safe areas by replacing
`env(safe-area-inset-top)` with 59px and `env(safe-area-inset-bottom)` with 34px in a copy of `docs/`. The real iPhone
home-screen app (iOS 26) behaves differently from the simulator for `position: fixed` at the bottom: test claims
against the owner's screenshots. Bump `theme.css?v=` (in `nav.js` and `sw.js`) and the service-worker cache name
(`sw.js`) when pages or CSS change.
