"""Remove published data files of instruments that are no longer in scripts/instruments.json."""
import glob
import json
import os
import re
import sys

data_dir = sys.argv[1] if len(sys.argv) > 1 else "docs/data"
keys = {i["key"] for i in json.load(open("scripts/instruments.json"))}
for path in glob.glob(os.path.join(data_dir, "*.json")):
    name = re.sub(r"^(scoreboard|intraday|news)-", "", os.path.basename(path)[:-5])
    if name != "index" and name not in keys:
        os.remove(path)
        print("removed", os.path.basename(path))
