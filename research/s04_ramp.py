from pathlib import Path
PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "data" / "interim" / "research"
OUT.mkdir(parents=True, exist_ok=True)
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
df = pd.read_pickle(str(OUT / "df2.pkl"))
df["rowidx"] = df.groupby("ts").cumcount()
out = {}
for c in ["pct_silica_conc", "pct_iron_conc", "pct_silica_feed", "pct_iron_feed"]:
    g = df.groupby("ts")[c]
    first = g.first(); last = g.last(); nun = g.nunique()
    varying = nun > 1
    # linearity of ramp: residual of linear fit within varying hours
    res = []
    for t in nun[varying].index[:400]:
        v = df.loc[df.ts == t, c].values
        x = np.arange(len(v))
        p = np.polyfit(x, v, 1)
        res.append(np.abs(v - np.polyval(p, x)).max())
    res = np.array(res)
    print(f"{c}: varying hours={int(varying.sum())}, max abs residual from linear fit (first 400): median={np.median(res):.2e}, max={res.max():.2e}")
    # next-hour test: does ramp end equal next hour's first value?
    idx = first.index
    nxt = pd.Series(first.values[1:], index=idx[:-1])  # next hour's row0 (only consecutive hours matter)
    dt = pd.Series(idx[1:] - idx[:-1], index=idx[:-1])
    consec = dt == pd.Timedelta("1h")
    vi = varying.reindex(idx[:-1]).fillna(False)
    m = vi & consec
    step = (last - first) / (nun.reindex(idx) - 1).replace(0, np.nan)
    endpoint_next = last.reindex(idx[:-1]) + step.reindex(idx[:-1])
    d_next = (endpoint_next[m] - nxt[m]).abs()
    d_first = (last.reindex(idx[:-1])[m] - first.reindex(idx[:-1])[m]).abs()
    print(f"  varying hours followed by consecutive hour: {int(m.sum())}")
    print(f"  |ramp end (last + step) - next hour row0|: median={d_next.median():.4f}, p90={d_next.quantile(.9):.4f}")
    print(f"  |last - first| within hour for those hours: median={d_first.median():.4f}")
    # run lengths of constant hourly value (hour level, first value), consecutive hours
    h = first.reindex(pd.date_range(idx.min(), idx.max(), freq="h"))
    same = (h == h.shift()) & h.notna() & h.shift().notna()
    runs = (~same).cumsum()
    rl = same.groupby(runs).sum() + 1
    rl = rl[h.groupby(runs).first().notna()]
    print(f"  hour-level run length of identical consecutive values: runs={len(rl)}, median={rl.median()}, p90={rl.quantile(.9):.0f}, max={rl.max()}")
    out[c] = rl
for c in ["pct_silica_feed", "pct_iron_feed"]:
    rl = out[c]
    print(c, "runs>=5h:", int((rl >= 5).sum()), " runs>=24h:", int((rl >= 24).sum()), " longest:", int(rl.max()), "h;", " hours in runs>=24h:", int(rl[rl >= 24].sum()))
# longest run dates for feeds
