"""Experiment mode "fii" (26 Oct 2026): do foreign investors' positions help the from-open signal?

26 Oct 2026: reports credited the rally partly to foreign investors (FIIs) buying ~Rs 888 crore of shares on Friday.
NSE publishes no free history of the daily FII / DII cash flows (only the latest day), but it does publish, every day,
each participant group's open positions in index futures and options (fao_participant_oi_<DDMMYYYY>.csv, the
"participant-wise open interest", back to 2016). Tested here, from the previous session's file (known before the open):
  fii_long    FIIs' share of long index-futures positions, long / (long + short): its change on the previous session
              and its level against the past 60 sessions, as two extra inputs
  agree       trade only when the change in fii_long agrees with the side (rising = bullish)
  client      the same two inputs for retail clients (often the other side of FIIs)
Rule fixed before the run (as vix_study): more per trade than the live signal in both halves and in total, and for
the filter, the skipped trades must lose.
"""
import io
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

import todaycall as tc
from accuracy_study import _wf_tiers
from pcr_probe import HEAD
from vix_study import passes, stats


def url(d):
    return f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d:%d%m%Y}.csv"


def parse(text):
    """{participant: long share of index futures} from one day's file."""
    df = pd.read_csv(io.StringIO(text), skiprows=1)
    df.columns = [str(c).strip() for c in df.columns]
    name = df.columns[0]
    out = {}
    for _, r in df.iterrows():
        who = str(r[name]).strip().upper()
        lo, sh = float(r["Future Index Long"]), float(r["Future Index Short"])
        if lo + sh > 0:
            out[who] = lo / (lo + sh)
    return out


def fetch(days):
    s = requests.Session()
    try:
        s.get("https://www.nseindia.com/", headers=HEAD, timeout=20)
    except Exception:
        pass

    def one(d):
        for _ in range(3):
            try:
                r = s.get(url(d), headers=HEAD, timeout=30)
                if r.status_code == 200:
                    return d, parse(r.text)
                if r.status_code == 404:
                    return d, None
            except Exception:
                pass
        return d, None
    with ThreadPoolExecutor(4) as ex:
        return dict(ex.map(one, days))


def features(series, df_index, days, pos):
    chg, z = [], []
    for d in df_index:
        prev = days[pos[d.date()] - 1]
        h = series[series.index <= prev]
        if len(h) > 20 and h.index[-1] == prev:
            chg.append(float(h.iloc[-1] - h.iloc[-2]))
            w = h.iloc[-60:]
            z.append(float((h.iloc[-1] - w.mean()) / (w.std() + 1e-9)))
        else:
            chg.append(0.0), z.append(0.0)
    return np.array(chg), np.array(z)


def main():
    try:
        nd = tc.daily()
        nd = nd[nd.index.date < pd.Timestamp.now(tz="Asia/Kolkata").date()]
        series = {k: tc.hourly(t) for k, t in {**tc.OVERNIGHT, **tc.INDIA}.items()}
        df = tc.history(nd, series)
        days = [d.date() for d in nd.index]
        pos = {d: i for i, d in enumerate(days)}
        want = days[max(0, days.index(df.index[0].date()) - 65):]
        got = fetch(want)
        ok = {d: v for d, v in got.items() if v}
        out = {"days": len(df), "from": str(df.index[0].date()), "to": str(df.index[-1].date()),
               "files_wanted": len(want), "files_downloaded": len(ok),
               "last": {str(d): ok[d] for d in sorted(ok)[-2:]}}
        if len(ok) < 0.8 * len(want):
            out["result"] = "too few files downloaded to test"
            print("STUDY fii " + json.dumps(out), flush=True)
            return
        fii = pd.Series({d: v.get("FII") for d, v in ok.items() if v.get("FII") is not None}).sort_index()
        cli = pd.Series({d: v.get("CLIENT") for d, v in ok.items() if v.get("CLIENT") is not None}).sort_index()
        df["fii_chg"], df["fii_z"] = features(fii, df.index, days, pos)
        df["cli_chg"], df["cli_z"] = features(cli, df.index, days, pos)
        out["rows_with_fii"] = int((df["fii_z"] != 0).sum())

        o2c = (1 + df["day"].values) / (1 + df["gap"].values) - 1
        p, tiers = _wf_tiers(df[tc.OPEN_FEATS].values, o2c)
        top = np.isin(tiers, tc.TRADE_TIERS)
        side = np.sign(p)
        pnl = side * o2c * 100 - tc.TRADE_COST_PCT
        live = stats(pnl[top])
        out["live"] = live
        for name, extra in (("fii_long", ["fii_chg", "fii_z"]), ("client", ["cli_chg", "cli_z"])):
            p2, t2 = _wf_tiers(df[tc.OPEN_FEATS + extra].values, o2c)
            top2 = np.isin(t2, tc.TRADE_TIERS)
            v = stats((np.sign(p2) * o2c * 100 - tc.TRADE_COST_PCT)[top2])
            v["passes"] = passes(v, live)
            out[f"input_{name}"] = v
        chg = df["fii_chg"].values
        skip = (chg != 0) & (np.sign(chg) != side)
        kept, skipped = stats(pnl[top & ~skip]), stats(pnl[top & skip])
        out["agree"] = {"kept": kept, "skipped": skipped,
                        "passes": passes(kept, live) and skipped.get("trades", 0) > 0 and skipped["avg_pct"] < 0}
        out["passed"] = [k for k, v in out.items() if isinstance(v, dict) and v.get("passes")]
        print("STUDY fii " + json.dumps(out), flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"STUDY fii failed: {e!r}", flush=True)
