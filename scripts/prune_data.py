"""Remove published data files of instruments that are no longer in scripts/instruments.json."""
import glob
import json
import os
import re
import sys

data_dir = sys.argv[1] if len(sys.argv) > 1 else "docs/data"
keys = {i["key"] for i in json.load(open("scripts/instruments.json"))}
# shared files that belong to no single instrument (4 Nov 2026: the 15:50 forecast run deleted options-live.json and
# data-health.json, which the name rule below took for instruments called "live" and "data-health")
KEEP = {"options-live.json", "options-nifty.json", "data-health.json", "paper-accounts.json"}
for path in glob.glob(os.path.join(data_dir, "*.json")):
    if os.path.basename(path).startswith(("replay-", "nextcandle-")) or os.path.basename(path) in KEEP:
        continue
    name = re.sub(r"^(scoreboard|intraday|news|today|hourly|live|daylike|gift|next|options)-", "", os.path.basename(path)[:-5])
    if name not in ("index", "status", "status-today", "history") and name not in keys:
        os.remove(path)
        print("removed", os.path.basename(path))
