"""Phone alerts on your own Kite positions (4 Nov 2026, asked by the user). Read-only: nothing is ever ordered.

The keeper (keeper.py) looks at your open NIFTY / BANKNIFTY option positions every 2 minutes during the session, once
there is a Kite login that day, and sends an alert (status.py's ntfy channel) when:
  - a position appears or changes size: what it is, your average price, the price now, and its alert levels;
  - the option's price crosses a level against your average price, once each a day:
      bought options: -20% (warning), -35% (stop), +30%, +60%;
      sold options:   +25% (warning), +50% (stop), -40%, -70% (decayed: profit);
  - a position is closed: its P&L for the day;
  - at 15:10 anything is still open (MIS positions are squared off by Zerodha at about 15:20).
Privacy: the repository and its logs are public, so positions go only to your phone. Nothing about them is written
to a file, a branch or the logs (the keeper prints only how many positions and alerts there were).
"""
from datetime import time

LONG_LEVELS = ((-0.35, "stop"), (-0.20, "warning"), (0.30, "up"), (0.60, "up"))
SHORT_LEVELS = ((0.50, "stop"), (0.25, "warning"), (-0.40, "profit"), (-0.70, "profit"))
SQUARE_OFF = time(15, 10)
FROM, TO = time(9, 15), time(15, 30)
UNDERLYINGS = ("NIFTY", "BANKNIFTY")


def fetch():
    """Kite's net positions, or None without a login."""
    import kite
    s = kite.session()
    if not s:
        return None
    return kite._req("/portfolio/positions", s[0], s[1])["data"]["net"]


def _rs(x):
    return f"{'+' if x > 0 else '-' if x < 0 else ''}Rs{abs(round(x)):,}"


def tracked(positions):
    """Open NIFTY / BANKNIFTY options (NFO), by tradingsymbol and product."""
    return {f"{p['tradingsymbol']}|{p['product']}": p for p in positions or []
            if p.get("exchange") == "NFO" and int(p.get("quantity") or 0) != 0
            and str(p.get("tradingsymbol", "")).startswith(UNDERLYINGS) and str(p["tradingsymbol"]).endswith(("CE", "PE"))}


def _desc(p):
    qty = int(p["quantity"])
    return f"{'Bought' if qty > 0 else 'Sold'} {p['tradingsymbol']} x{abs(qty)} ({p['product']})"


def check(positions, state, now, silent=False):
    """(alerts, state). alerts: [(kind, headline, text)]; state lives in the keeper's memory for the day.
    silent=True records what is already true without alerting (a keeper taking over from another one)."""
    day = now.date().isoformat()
    if state.get("date") != day:
        state = {"date": day, "seen": {}, "square_off": False}
    out = []
    cur = tracked(positions)
    total = sum(float(p.get("pnl") or 0) for p in cur.values())
    for k, p in cur.items():
        qty, avg, ltp = int(p["quantity"]), float(p.get("average_price") or 0), float(p.get("last_price") or 0)
        s = state["seen"].get(k)
        levels = LONG_LEVELS if qty > 0 else SHORT_LEVELS
        if s is None or s["qty"] != qty:
            s = state["seen"][k] = {"qty": qty, "avg": avg, "hit": [], "closed": False}
            lv = ", ".join(f"{'+' if x > 0 else ''}{x * 100:.0f}% ({avg * (1 + x):,.1f}{' ' + w if w in ('stop',) else ''})" for x, w in levels)
            out.append(("position", f"Tracking: {_desc(p)}",
                        f"Average Rs{avg:,.2f}, now Rs{ltp:,.2f}, P&L {_rs(float(p.get('pnl') or 0))}. Alerts at {lv}."))
        if avg <= 0 or ltp <= 0:
            continue
        chg = ltp / avg - 1
        for x, what in levels:
            if x not in s["hit"] and (chg <= x if x < 0 else chg >= x):
                s["hit"].append(x)
                kind = "position_stop" if what == "stop" else "position"
                head = {"stop": "STOP level", "warning": "Warning", "up": "Up", "profit": "Profit"}[what]
                out.append((kind, f"{head}: {p['tradingsymbol']} {'+' if chg > 0 else ''}{chg * 100:.0f}%",
                            f"{_desc(p)}: average Rs{avg:,.2f}, now Rs{ltp:,.2f} ({'+' if chg > 0 else ''}{chg * 100:.1f}%), "
                            f"P&L {_rs(float(p.get('pnl') or 0))}. All open positions {_rs(total)}."))
    allpos = {f"{p['tradingsymbol']}|{p['product']}": p for p in positions or []}
    for k, s in state["seen"].items():
        if k not in cur and not s["closed"]:
            s["closed"] = True
            pnl = float((allpos.get(k) or {}).get("pnl") or 0)
            out.append(("position", f"Closed: {k.split('|')[0]}", f"P&L today {_rs(pnl)}."))
    if cur and now.time() >= SQUARE_OFF and not state["square_off"]:
        state["square_off"] = True
        mis = [p["tradingsymbol"] for p in cur.values() if p.get("product") == "MIS"]
        out.append(("position_stop", "15:10: positions still open",
                    "; ".join(f"{_desc(p)} {_rs(float(p.get('pnl') or 0))}" for p in cur.values())
                    + f". Total {_rs(total)}." + (f" Intraday (MIS): {', '.join(mis)} - Zerodha squares these off at about 15:20." if mis else "")))
    return ([] if silent else out), state


class Watcher:
    """The keeper's position check: every call looks at most once every `every` seconds, within the session."""

    def __init__(self, every=120, fetch_fn=None, notify_fn=None, refresh_fn=None, silent_first=False):
        self.every, self.fetch, self.state, self.last = every, fetch_fn or fetch, {}, 0.0
        self.notify, self.refresh, self.silent = notify_fn, refresh_fn, silent_first

    def check(self, now):
        import time as _t
        if not FROM <= now.time() <= TO or _t.time() - self.last < self.every:
            return 0
        self.last = _t.time()
        pos = self.fetch()
        if pos is None:                                   # no login yet: look for one (the login page may be used now)
            if self.refresh:
                self.refresh()
            return 0
        alerts, self.state = check(pos, self.state, now, silent=self.silent)
        self.silent = False
        if self.notify is None:
            import status
            self.notify = lambda a: status.notify({"kind": a[0], "headline": a[1], "reason": a[2], "body": f"{a[1]}\n{a[2]}"})
        for a in alerts:
            self.notify(a)
        print(f"{now:%H:%M:%S} IST  positions: {len(tracked(pos))} open, {len(alerts)} alert(s)", flush=True)
        return len(alerts)
