"""Start the "Intraday nowcast" workflow at fixed IST times during the NSE session, then the post-close forecast
(predict.yml) at 15:50 (run by keeper.yml).

The first update is the pre-open call, which only counts if it is made before 09:15. Times already passed when the
keeper starts are skipped, except that the most recent one is run straight away so a late start still gives an update.

At 09:08 it checks that the 08:57 call reached the Status page (status.json on site-data dated today, past "pending").
If not, the phone gets a "no signal today" warning (status.py's Telegram / ntfy channels), so silence never hides a
failure, and the nowcast is started once more.
"""
import json
import os
import subprocess
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
TIMES = ["08:57", "09:50", "10:20", "11:05", "11:50", "12:35", "13:20", "14:05", "14:50", "15:50"]
WATCHDOG = "09:08"
RETRY_WAIT = 300                                # seconds the retry gets before the warning (~09:13)
SIGNAL_KINDS = ("no_trade", "call", "put", "hold", "sell")
AFTER_CLOSE = "15:50"                           # the post-close forecast (predict.yml); GitHub dropped its cron on 15 Oct
MAX_RUN = timedelta(hours=5, minutes=50)        # stay inside the job's time limit


def at(now, hm):
    h, m = map(int, hm.split(":"))
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


def dispatch(label, workflow="intraday.yml"):
    r = subprocess.run(["gh", "workflow", "run", workflow, "--ref", "main"], capture_output=True, text=True)
    print(f"{datetime.now(IST):%H:%M:%S} IST  {label}: {'started' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()}",
          flush=True)


def signal_ok(status, today):
    """Did today's pre-open call reach the Status page?"""
    return bool(status) and status.get("date") == today and status.get("kind") in SIGNAL_KINDS


def live_status():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    r = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw",
                        f"repos/{repo}/contents/status.json?ref=site-data"], capture_output=True, text=True)
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
    for s, what in plan:
        if s - start > MAX_RUN:
            hand_over()
            break
        time.sleep(max(0.0, (s - datetime.now(IST)).total_seconds()))
        if what == "watchdog":
            watchdog()
        else:
            dispatch(f"{s:%H:%M}", "predict.yml" if f"{s:%H:%M}" == AFTER_CLOSE else "intraday.yml")


if __name__ == "__main__":
    main()
