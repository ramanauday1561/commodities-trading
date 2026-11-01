"""NIFTY option prices from the bhavcopy (both formats) and the option study's pricing (no network)."""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import option_data as od  # noqa: E402
import option_study as os_  # noqa: E402

D = date(2026, 10, 29)


def zipped(df):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("bhav.csv", df.to_csv(index=False))
    return b.getvalue()


def udiff():
    rows = [{"TckrSymb": "NIFTY", "FinInstrmTp": "IDF", "XpryDt": "2026-11-25", "StrkPric": "", "OptnTp": "", "OpnPric": 22950,
             "HghPric": 23050, "LwPric": 22900, "ClsPric": 23000.0, "SttlmPric": 23000, "OpnIntrst": 1, "TtlTradgVol": 10}]
    for e in ("2026-10-29", "2026-11-04", "2026-11-11", "2026-11-18"):
        for k in (21000, 22950, 23000, 23050, 25000):
            for t in ("CE", "PE"):
                rows.append({"TckrSymb": "NIFTY", "FinInstrmTp": "IDO", "XpryDt": e, "StrkPric": k, "OptnTp": t, "OpnPric": 100,
                             "HghPric": 120, "LwPric": 80, "ClsPric": 110, "SttlmPric": 110, "OpnIntrst": 5, "TtlTradgVol": 3})
    rows.append({**rows[-1], "TckrSymb": "BANKNIFTY"})
    return pd.DataFrame(rows)


def old():
    rows = [{"INSTRUMENT": "FUTIDX", "SYMBOL": "NIFTY", "EXPIRY_DT": "27-Jun-2019", "STRIKE_PR": 0, "OPTION_TYP": "XX", "OPEN": 1,
             "HIGH": 1, "LOW": 1, "CLOSE": 11900.0, "SETTLE_PR": 1, "CONTRACTS": 5, "OPEN_INT": 1}]
    for k in (11800, 11900, 12000, 13000):
        for t in ("CE", "PE"):
            rows.append({"INSTRUMENT": "OPTIDX", "SYMBOL": "NIFTY", "EXPIRY_DT": "06-Jun-2019", "STRIKE_PR": k, "OPTION_TYP": t,
                         "OPEN": 50, "HIGH": 60, "LOW": 40, "CLOSE": 55, "SETTLE_PR": 55, "CONTRACTS": 0 if k == 12000 else 9,
                         "OPEN_INT": 3})
    return pd.DataFrame(rows)


class Data(unittest.TestCase):
    def test_udiff_keeps_nifty_near_the_money_and_three_expiries(self):
        df = od.parse(zipped(udiff()), D)
        self.assertEqual(sorted(df["expiry"].astype(str).unique()), ["2026-10-29", "2026-11-04", "2026-11-11"])
        self.assertEqual(sorted(df["strike"].unique()), [22950, 23000, 23050])       # 21000 / 25000 are >6% away
        self.assertEqual(df["fut"].iloc[0], 23000.0)
        self.assertEqual(list(df.columns), od.COLS)

    def test_old_format_drops_untraded_strikes(self):
        df = od.parse(zipped(old()), date(2019, 6, 3))
        self.assertEqual(sorted(df["strike"].unique()), [11800, 11900])
        self.assertEqual(str(df["expiry"].iloc[0]), "2019-06-06")

    def test_update_saves_months_and_missing_days(self):
        d = tempfile.mkdtemp()
        frame = od.parse(zipped(udiff()), D)
        get = lambda day: (day, frame.assign(d=day) if day.day % 2 else None)
        od.update(d, 5, 0, 1, today=date(2015, 1, 8), get=get)
        self.assertEqual(sorted(od.stored(d)), ["2015-01-01", "2015-01-02", "2015-01-05", "2015-01-06", "2015-01-07"])
        self.assertEqual(sorted({str(x) for x in od.load([d])["d"]}), ["2015-01-01", "2015-01-05", "2015-01-07"])


class Pricing(unittest.TestCase):
    def setUp(self):
        self.ch = od.parse(zipped(udiff()), D)

    def test_pick_by_expiry_rule_and_strike(self):
        self.assertEqual(str(os_.pick(self.ch, D, 22990, "CE", "nearest")["expiry"]), "2026-10-29")      # expiry day
        self.assertEqual(str(os_.pick(self.ch, D, 22990, "CE", "no_expiry_day")["expiry"]), "2026-11-04")
        self.assertEqual(str(os_.pick(self.ch, D, 22990, "CE", "next")["expiry"]), "2026-11-11")
        self.assertEqual(os_.pick(self.ch, D, 22990, "CE", "no_expiry_day")["strike"], 23000)
        self.assertEqual(os_.pick(self.ch, D, 22990, "CE", "no_expiry_day", otm=1)["strike"], 23050)
        self.assertEqual(os_.pick(self.ch, D, 22990, "PE", "no_expiry_day", otm=1)["strike"], 22950)
        self.assertIsNone(os_.pick(self.ch, D, 22990, "PE", "no_expiry_day", otm=2))

    def test_signal_trades_are_priced_open_to_close_after_costs(self):
        nd = pd.DataFrame({"open": [22990.0], "close": [23090.0], "high": [1.0], "low": [1.0]}, index=[pd.Timestamp(D)])
        out = os_.signal_in_options({D: 1}, self.ch, nd)
        self.assertEqual(out["ATM, skip expiry day"]["avg_pts"], round(110 - 100 - os_.COST, 2))
        self.assertEqual(out["half-delta estimate, same days"]["avg_pts"], round(0.5 * 100 - os_.COST, 2))
        self.assertFalse(out["worth_trading_in_options"])                          # one trade is not enough

    def test_straddles_and_picking_run_on_a_year_and_more(self):
        days = pd.bdate_range("2023-01-02", "2025-06-30")
        rng = np.random.default_rng(0)
        px = 18000 * np.exp(np.cumsum(rng.normal(0, 0.008, len(days))))
        nd = pd.DataFrame({"open": px * (1 + rng.normal(0, 0.002, len(days))), "close": px, "high": px * 1.006,
                           "low": px * 0.994}, index=days)
        vix = pd.Series(14 + rng.normal(0, 1, len(days)), index=[t.date() for t in days])
        rows = []
        for t, o in zip(days, nd["open"]):
            k = round(o / 50) * 50
            for typ in ("CE", "PE"):
                op = 100.0
                rows.append({"d": t.date(), "expiry": (t + pd.Timedelta(days=7)).date(), "strike": k, "type": typ,
                             "open": op, "high": 0, "low": 0, "close": op * (1 + rng.normal(-0.1, 0.4)), "settle": 0,
                             "oi": 1, "volume": 1, "fut": o})
        st = os_.straddles(pd.DataFrame(rows), nd, vix, {})
        self.assertGreater(len(st), 500)
        out = os_.picking(st)
        self.assertGreater(out["model top 20%"]["trades"], 50)
        self.assertIn("picking_works", out)
        self.assertGreater(os_.vix_vs_moves(nd, vix)["days"], 500)


if __name__ == "__main__":
    unittest.main()
