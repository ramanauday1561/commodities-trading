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
    dm = d.get("default_model", "base")
    first = d["models"].get(dm, d["models"]["base"])["forecast"][0]
    times = [c["time"] for c in d.get("candles", [])]
    i = times.index(d["last_date"]) if d.get("last_date") in times else -1
    day_pct = (round((d["candles"][i]["close"] / d["candles"][i - 1]["close"] - 1) * 100, 2)   # the last completed day's move
               if i >= 1 else None)
    out.append({"key": inst["key"], "name": inst["name"], "group": inst["group"], "unit": inst["unit"], "about": inst.get("about", ""),
                "change_pct": round((first["close"] - d["last_close"]) / d["last_close"] * 100, 2),
                "day_pct": day_pct, "prob_up": first["prob_up"], "updated": d["updated"]})
if not out:
    raise SystemExit("no instrument data produced")
json.dump(out, open("docs/data/index.json", "w"), separators=(",", ":"))
print(f"manifest: {len(out)} instruments")
