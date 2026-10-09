"""Backtest helpers shared by the Kronos and LightGBM models so all models are scored identically."""
import numpy as np

BT_SPREAD = 100           # backtest days spread evenly across the whole history
BT_RECENT = 50            # plus the most recent days


def backtest_indices(n, start):
    """Days to evaluate: BT_SPREAD spread over [start, n) plus the last BT_RECENT. None if history is too short."""
    if n - BT_RECENT - 1 <= start:
        return None
    spread = np.linspace(start, n - BT_RECENT - 1, BT_SPREAD).astype(int).tolist()
    return sorted(set(spread + list(range(n - BT_RECENT, n))))


def summarize(r):
    """r rows: (day index, previous close, actual close, predicted close)."""
    prev, actual, pred = r[:, 1], r[:, 2], r[:, 3]
    return {
        "days": int(len(r)),
        "direction_accuracy": round(float(((pred > prev) == (actual > prev)).mean()), 3),
        "up_rate": round(float((actual > prev).mean()), 3),                       # baseline: always guess "up"
        "mape_pct": round(float((np.abs(pred - actual) / actual).mean() * 100), 3),
        "naive_mape_pct": round(float((np.abs(prev - actual) / actual).mean() * 100), 3),  # "same as yesterday"
    }


def full_stats(r, n, index):
    """Backtest stats plus the (p10, p90) quantiles of actual/predicted - 1, used to calibrate forecast ranges."""
    err = r[:, 2] / r[:, 3] - 1
    stats = {"all": summarize(r), "recent": summarize(r[r[:, 0] >= n - BT_RECENT]),
             "span": [index[int(r[0, 0])].strftime("%Y-%m-%d"), index[int(r[-1, 0])].strftime("%Y-%m-%d")]}
    stats["days"] = stats["all"]["days"]
    return stats, (float(np.percentile(err, 10)), float(np.percentile(err, 90)))
