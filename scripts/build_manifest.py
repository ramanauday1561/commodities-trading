"""Build docs/data/index.json (instrument list + one-line summaries) from the per-instrument files."""
import json
import os

out = []
for inst in json.load(open("scripts/instruments.json")):
    path = f"docs/data/{inst['key']}.json"
    if not os.path.exists(path):
        print("missing:", inst["key"])
        continue
    d = json.load(open(path))
    first = d["forecast"][0]
    out.append({"key": inst["key"], "name": inst["name"], "group": inst["group"], "unit": inst["unit"],
                "change_pct": round((first["close"] - d["last_close"]) / d["last_close"] * 100, 2),
                "prob_up": first["prob_up"], "updated": d["updated"]})
if not out:
    raise SystemExit("no instrument data produced")
json.dump(out, open("docs/data/index.json", "w"), separators=(",", ":"))
print(f"manifest: {len(out)} instruments")
