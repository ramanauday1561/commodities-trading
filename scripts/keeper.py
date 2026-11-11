"""Start the "Intraday nowcast" workflow at fixed IST times during the NSE session, then the post-close forecast
(predict.yml) at 15:50 (run by keeper.yml).

The first update is the pre-open call, which only counts if it is made before 09:15. Times already passed when the
keeper starts are skipped, except that the most recent one is run straight away so a late start still gives an update.

At 09:08 it checks that the 08:57 call reached the Status page (status.json on site-data dated today, past "pending").
If not, the phone gets a "no signal today" warning (status.py's ntfy channel), so silence never hides a
failure, and the nowcast is started once more.

Your positions (positions.py, 4 Nov 2026): with that day's Kite login, every 2 minutes from 09:15 to 15:30 it looks
at your open NIFTY / BANKNIFTY options and alerts the phone (levels, closes, a 15:10 reminder). Without a login it
looks for one every 5 minutes (the Kite login page can be used at any time). Nothing about positions is printed.

Stop watcher: on a trade day (status.json kind call / put / hold) it looks at NIFTY's 1-minute candles every 5 minutes
from 09:20 to 15:10 and starts the nowcast at once when NIFTY has moved status.STOP_PCT against the trade from the
open. That run's status.py sees the same high / low, switches the page to SELL (kind "stop") and sends the alert, so
the page, the journal and the phone stay in step and nothing is sent twice.
"""
import json
import os
import subprocess
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
TIMES = (["08:57"] + [f"{m // 60:02d}:{m % 60:02d}" for m in range(9 * 60 + 25, 15 * 60 + 26, 10)]   # every 10 min
         + ["15:50"])                           # 09:25 ... 15:25 (27 Oct 2026: the live chart), then the post-close run
WATCHDOG = "09:08"
RETRY_WAIT = 300                                # seconds the retry gets before the warning (~09:13)
WATCH_EVERY = 300                               # stop watcher: seconds between looks at the price
WATCH_FROM, WATCH_TO = "09:20", "15:10"
SIGNAL_KINDS = ("no_trade", "call", "put", "hold", "sell")
AFTER_CLOSE = "15:50"                           # the post-close forecast (predict.yml); GitHub dropped its cron on 15 Oct
MAX_RUN = timedelta(hours=5, minutes=50)        # stay inside the job's time limit


def at(now, hm):
    h, m = map(int, hm.split(":"))
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


VPS_FRESH, VPS_FRESH_MORNING = timedelta(minutes=15), timedelta(hours=20)


def vps_active(runner, now):
    """11 Nov 2026: the order server (VPS) runs the 10-minute updates itself and writes runner.json to site-data each
    run. While it is fresh this keeper leaves those runs to it (two runs at once would write over each other); if it
    goes quiet for 15 minutes the keeper takes over again. Before 09:00 last session's runs count (no run since
    15:25 yesterday), so the 08:57 call is not made twice."""
    try:
        at_ = datetime.fromisoformat((runner or {})["at"])
    except (KeyError, TypeError, ValueError):
        return False
    limit = VPS_FRESH_MORNING if now.strftime("%H:%M") < "09:00" else VPS_FRESH
    return (runner or {}).get("by") == "vps" and timedelta(0) <= now - at_ <= limit


def dispatch(label, workflow="intraday.yml"):
    if workflow == "intraday.yml" and vps_active(site_json("runner.json"), datetime.now(IST)):
        print(f"{datetime.now(IST):%H:%M:%S} IST  {label}: the VPS runs the updates; not started here", flush=True)
        return
    r = subprocess.run(["gh", "workflow", "run", workflow, "--ref", "main"], capture_output=True, text=True)
    print(f"{datetime.now(IST):%H:%M:%S} IST  {label}: {'started' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()}",
          flush=True)


def signal_ok(status, today):
    """Did today's pre-open call reach the Status page?"""
    return bool(status) and status.get("date") == today and status.get("kind") in SIGNAL_KINDS


def live_status():
    return site_json("status.json")


def site_json(name):
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    r = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw",
                        f"repos/{repo}/contents/{name}?ref=site-data"], capture_output=True, text=True)
    try:
        return json.loads(r.stdout) if r.returncode == 0 else None
    except ValueError:
        return None


def watchdog(wait=RETRY_WAIT):
    """09:08: if the call is missing, start the nowcast again and give it until ~09:13 before warning the phone
    (a run queued for a few minutes at GitHub must not raise a false alarm)."""
    today = datetime.now(IST).date().isoformat()
    st = live_status()
    if not signal_ok(st, today):
        print(f"{datetime.now(IST):%H:%M:%S} IST  watchdog: no call on the Status page yet", flush=True)
        dispatch("retry after the watchdog")
        time.sleep(wait)
        st = live_status()
    if signal_ok(st, today):
        print(f"{datetime.now(IST):%H:%M:%S} IST  watchdog: today's call is on the Status page ({st.get('state')})", flush=True)
        return True
    import status
    res = status.notify({"kind": "warning", "body": "The 08:57 call did not reach the Status page, so there is no "
                         "trade signal today: do not trade on the app today. (Status page last updated: "
                         f"{(st or {}).get('updated', 'unknown')})"})
    print(f"{datetime.now(IST):%H:%M:%S} IST  watchdog: NO SIGNAL, warning {res or 'not sent (no channel configured)'}", flush=True)
    return False


def day_range():
    """Today's open and the high / low since, from NIFTY's 1-minute candles (None if unavailable)."""
    import prices
    raw = prices.download("^NSEI", period="1d", interval="1m", auto_adjust=False, progress=False)
    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
    raw = raw.dropna(subset=["High", "Low"])
    if not len(raw) or raw.index[-1].tz_convert(IST).date() != datetime.now(IST).date():
        return None
    return float(raw["Open"].iloc[0]), float(raw["High"].max()), float(raw["Low"].min())


class StopWatcher:
    def __init__(self, status_fn=None, range_fn=None):
        self.status_fn, self.range_fn = status_fn or live_status, range_fn or day_range
        self.done = False
        self.last_start = None

    def check(self):
        """One look; returns True when it started a run because the stop was reached."""
        if self.done:
            return False
        import status
        st = self.status_fn()
        today = datetime.now(IST).date().isoformat()
        if st and st.get("date") == today and st.get("kind") in ("no_trade", "stop", "sell", "closed"):
            self.done = True                            # no trade today, or the trade is already over
            return False
        if not st or st.get("date") != today or st.get("kind") not in ("call", "put", "hold") or not st.get("side"):
            return False
        if self.last_start and datetime.now(IST) - self.last_start < timedelta(minutes=10):
            return False                                # the run it started has not updated the page yet
        r = self.range_fn()
        if r and status.stop_hit(st["side"], *r):
            dispatch(f"stop reached for the {st['side']} (open {r[0]:,.2f}, high {r[1]:,.2f}, low {r[2]:,.2f})")
            self.last_start = datetime.now(IST)         # done once the page shows the stop (kind "stop")
            return True
        return False


_LOOKED = [0.0]


def wait_until(t, watcher=None, positions=None):
    """Sleep until t; inside the watch window, look at the stop every WATCH_EVERY seconds on the way, and at your
    positions every 2 minutes (positions.Watcher keeps its own pace)."""
    while True:
        now = datetime.now(IST)
        if now >= t:
            return
        if watcher and at(now, WATCH_FROM) <= now <= at(now, WATCH_TO) and time.time() - _LOOKED[0] >= WATCH_EVERY:
            _LOOKED[0] = time.time()
            try:
                watcher.check()
            except Exception as e:                      # the watcher must never stop the keeper
                print(f"{now:%H:%M:%S} IST  stop watcher error: {e!r}", flush=True)
        if positions:
            try:
                positions.check(now)
            except Exception as e:                      # nor the position check (its error says no position detail)
                print(f"{now:%H:%M:%S} IST  positions check error: {type(e).__name__}", flush=True)
        time.sleep(max(0.0, min(60, (t - datetime.now(IST)).total_seconds())))


_PULLED = [0.0]


def refresh_kite():
    """Pull the kite-session branch again (the Kite login can happen after the keeper started), every 5 minutes at most."""
    if not os.environ.get("KITE_DIR") or time.time() - _PULLED[0] < 300:
        return
    _PULLED[0] = time.time()
    subprocess.run(["bash", "scripts/store.sh", "pull", "kite-session", os.environ["KITE_DIR"]], capture_output=True)
    import kite
    kite._SESSION.clear()


def hand_over():
    """Near the job's time limit: start a fresh keeper for the remaining update times, then exit."""
    r = subprocess.run(["gh", "workflow", "run", "keeper.yml", "--ref", "main", "-f", "handoff=1"],
                       capture_output=True, text=True)
    print(f"{datetime.now(IST):%H:%M:%S} IST  handed over to a new keeper: "
          f"{'ok' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()}", flush=True)


def main():
    start = datetime.now(IST)
    slots = [at(start, t) for t in TIMES]
    due = [s for s in slots if s > start]
    passed = [s for s in slots if s <= start]
    if passed and start - passed[-1] < timedelta(minutes=40) and not os.environ.get("HANDOFF"):   # a handoff has no gap
        last = f"{passed[-1]:%H:%M}"
        dispatch(f"catch-up for {last}", "predict.yml" if last == AFTER_CLOSE else "intraday.yml")
    check = at(start, WATCHDOG)
    plan = sorted([(s, "run") for s in due] + ([(check, "watchdog")] if check > start else []))
    watcher = StopWatcher()
    import positions
    pos = positions.Watcher(refresh_fn=refresh_kite, silent_first=bool(os.environ.get("HANDOFF"))) \
        if os.environ.get("KITE_API_KEY") else None
    for s, what in plan:
        if s - start > MAX_RUN:
            hand_over()
            break
        wait_until(s, watcher, pos)
        if what == "watchdog":
            watchdog()
        else:
            dispatch(f"{s:%H:%M}", "predict.yml" if f"{s:%H:%M}" == AFTER_CLOSE else "intraday.yml")


if __name__ == "__main__":
    main()
