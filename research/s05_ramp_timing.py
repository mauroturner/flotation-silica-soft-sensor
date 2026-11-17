from pathlib import Path
PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "data" / "interim" / "research"
OUT.mkdir(parents=True, exist_ok=True)
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
df = pd.read_pickle(str(OUT / "df2.pkl"))
g = df.groupby("ts")
for c in ["pct_silica_conc", "pct_iron_conc", "pct_silica_feed", "pct_iron_feed"]:
    nun = g[c].nunique()
    first = g[c].first()
    print(f"== {c}: varying hours={int((nun>1).sum())}")
    if (nun > 1).sum():
        vh = nun[nun > 1].index
        print("  varying hours by month:", vh.to_period("M").value_counts().sort_index().to_dict())
        # longest consecutive run of varying hours
        flag = (nun > 1).reindex(pd.date_range(first.index.min(), first.index.max(), freq="h"), fill_value=False)
        grp = (flag != flag.shift()).cumsum()
        rl = flag.groupby(grp).agg(["first", "size"])
        rl = rl[rl["first"]]["size"]
        print("  consecutive varying-hour runs: n=%d, median=%d, max=%d" % (len(rl), rl.median(), rl.max()))
    # for constant hours: difference between this hour and next hour's value
    idx = first.index
    consec = (idx[1:] - idx[:-1]) == pd.Timedelta("1h")
    diff_next = (first.shift(-1) - first)[:-1][consec]
    cons_mask = (nun == 1).reindex(idx)[:-1][consec]
    d_const = diff_next[cons_mask.values].abs()
    d_var = diff_next[~cons_mask.values].abs()
    print("  |next-hour first - this-hour first|: constant hours median=%.4f (n=%d); varying hours median=%.4f (n=%d)" % (
        d_const.median(), len(d_const), d_var.median() if len(d_var) else float('nan'), len(d_var)))
    print("  share of consecutive hour pairs where value unchanged: %.4f" % ((diff_next.abs() == 0).mean()))
