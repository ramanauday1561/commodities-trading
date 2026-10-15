"""Start the "Intraday nowcast" workflow at fixed IST times during the NSE session, then the post-close forecast
(predict.yml) at 15:50 (run by keeper.yml).

The first update is the pre-open call, which only counts if it is made before 09:15. Times already passed when the
keeper starts are skipped, except that the most recent one is run straight away so a late start still gives an update.
"""
import os
import subprocess
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
TIMES = ["08:57", "09:50", "10:20", "11:05", "11:50", "12:35", "13:20", "14:05", "14:50", "15:50"]
AFTER_CLOSE = "15:50"                           # the post-close forecast (predict.yml); GitHub dropped its cron on 15 Oct
MAX_RUN = timedelta(hours=5, minutes=50)        # stay inside the job's time limit


def at(now, hm):
    h, m = map(int, hm.split(":"))
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


def dispatch(label, workflow="intraday.yml"):
    r = subprocess.run(["gh", "workflow", "run", workflow, "--ref", "main"], capture_output=True, text=True)
    print(f"{datetime.now(IST):%H:%M:%S} IST  {label}: {'started' if r.returncode == 0 else 'FAILED ' + r.stderr.strip()}",
          flush=True)


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
    for s in due:
        if s - start > MAX_RUN:
            hand_over()
            break
        time.sleep(max(0.0, (s - datetime.now(IST)).total_seconds()))
        dispatch(f"{s:%H:%M}", "predict.yml" if f"{s:%H:%M}" == AFTER_CLOSE else "intraday.yml")


if __name__ == "__main__":
    main()
