# Working on this repo with Claude

Read this first, then `notes/HANDOFF.md` (the full history: what was built, tested, decided and why), `README.md`
(pages, workflows, data branches) and `STUDIES.md` (every backtest and its result).

## The project in one paragraph

A NIFTY options trading *information* app: a static site on GitHub Pages (`docs/`) that the owner installs on an iPhone
home screen, with GitHub Actions doing all the work (no server). It shows forecasts, a 09:15 signal, a live chart,
the "Next 10 minutes" lean (the screen watched all day), real Kite option prices, paper accounts and an honest record
of every call. Prices come from Zerodha Kite Connect (market data only) after a daily login, Yahoo otherwise.

## Rules the owner set (always follow)

- **Orders only through the order server, only for the owner's own picks.** Order placement (`server/`, the Orders
  page) was built on 5 Nov 2026 (#102), removed the same day on request (#104), and **brought back on 10 Nov 2026 at
  the owner's request** to trade real money, on a Hostinger VPS in Mumbai (Zerodha needs a whitelisted
  static IP for API orders). GitHub Actions and the pages never place orders. **On 11 Nov 2026 the owner asked for
  the ★ leans to be traded automatically** ("make it place orders automatically, don't wait for me"): with
  `AUTO_STAR=1` in `/etc/nifty-orders.env` the server buys each new ★ lean by itself (`Auto`: ATM option of the next
  expiry, 1 lot, stop 10% under, out after 30 minutes, each lean once). `AUTO_STAR=practice` does the same on paper at
  Kite's live prices with no orders. The server makes the lean itself too (`LocalLeans`: 15 s after each 10-minute
  candle, same code and morning model; replayed 33 of 33 on 11 Nov), as well as reading GitHub's. It is off unless the owner turns it on; nothing
  else the app suggests (plain leans, the 09:15 signal, the straddle) becomes an order. ★ leans failed every backtest
  (-₹53 to -₹72 a lot a trade). Keep the server's limits (lots a pick, open picks, loss a day), the passcode and LIMIT
  orders only.
- **Secrets live only in GitHub secrets** (and, for the order server, in `/etc/nifty-orders.env` on the VPS; since
  11 Nov 2026 with the owner's OK also the market-update keys in `/etc/nifty-market.env`: a fine-grained GitHub token
  with Contents read/write on this repo, xAI, FRED, ntfy; all entered by the owner in `setup.sh`) (`KITE_API_KEY`, `KITE_API_SECRET`, `FRED_API_KEY`, `XAI_API_KEY`,
  `NTFY_TOPIC`; Kaggle keys, if ever, only as `KAGGLE_USERNAME` / `KAGGLE_KEY`).
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
  15:15 and 15:20 5-minute bars are flat and the 15:25 bar jumps to the close. Not a data bug. The last lean is 15:05,
  and the live leans record does not count older 15:15 leans.

## Running a study or a check in a Claude cloud session

- Yahoo is blocked there and the Kite keys are not available (they stay in GitHub secrets; do not ask for them). Use
  the repo's data branches instead: `git fetch origin <branch>` then `git archive FETCH_HEAD | tar -x -C <dir>` for
  `options-data-p0..3` (bhavcopy option prices), `intraday-data` (5-minute NIFTY; Kite's candles since 19 May 2026),
  `options-live` (Kite quotes, option candles, paper trades), `scoreboard` (the live day files) and `site-data` (what
  the pages show). Point `OPTIONS_DIRS`, `INTRADAY_DIR` and `OPTLIVE_DIR` at the copies.
- New studies should read NIFTY's daily open from the stored 5-minute history, not Yahoo, so they run in both places.
- Commit the study with its pass rule first, run it, then commit the result (see `straddle_recent_study.py`, #116).
  Confirm on GitHub with **Model experiments** (`experiment.yml`, input `mode`), dispatched from `dev`.
- The **Hostinger** connector (claude.ai, remote MCP `https://mcp.hostinger.com`, owner's sign-in) can read and
  change the VPS (id 2147705, KVM 1, Mumbai, IP 189.72.149.115). Read freely; restart, rebuild, firewall or OS
  changes only when the owner asks. It never sees the Kite keys or the Orders passcode.
- **The VPS runs the 10-minute updates** (11 Nov 2026, `server/market_run.sh` on the `nifty-market` timer) and writes
  `runner.json` to site-data; `keeper.py` (`vps_active`) and `intraday.yml`'s fallback skip their runs while it is
  under 15 minutes old, and take over when it stops. The pages read data from the VPS (`/data/`) while it is fresh
  (`fresh.js`), else GitHub. The Kite page logs in on the VPS first (`/api/kite-login`), else GitHub's job.
  GitHub keeps the website, the 15:50 run and training, studies, the keeper's position alerts and stop watcher.
- The claude branch is reused: after each PR is merged, restart it from `dev` before the next change.

## Design rule: 60-30-10 colours (owner, 11 Nov 2026)

- **60% Desert Sand** `#EDC9AF`: the page; cards `#F7E8D8`, inputs `#FBF3EA`.
- **30% Olive Drab** `#4B5320`: the tab bar and the status-bar strip (`#434A1C`), headings, text (`#2B2F14`, muted
  `#57532F`), borders (olive at low alpha).
- **10% Signal Yellow** `#F9A900`: the active tab, the main (filled) buttons, switches when on, a selected chip. Never
  as text on sand (too light); dark text on it.
- Gains and losses keep their own colours (up `#185C3B`, down `#A3261F`); chart lines blue `#24529C`, purple
  `#6A3D9A`, amber `#7A4E00`. Every text colour is 4.5:1 or more on sand and on cards: check new ones.
- The tokens live in `docs/theme.css` (`--sand`, `--olive`, `--yellow`, and Glisse's `--lg-*` in light mode, set by
  `nav.js` with `data-theme="light"`); the pages' own `--bg / --text / --muted ...` use the same values.

## Checking UI changes

Use Playwright (pre-installed Chromium) at iPhone 14 size 393x852, simulating the safe areas by replacing
`env(safe-area-inset-top)` with 59px and `env(safe-area-inset-bottom)` with 34px in a copy of `docs/` (put the
`site-data` branch's files in its `data/` folder to see real numbers). The real iPhone
home-screen app (iOS 26) behaves differently from the simulator for `position: fixed` at the bottom: test claims
against the owner's screenshots. Bump `theme.css?v=` (in `nav.js` and `sw.js`) and the service-worker cache name
(`sw.js`) when pages or CSS change.
