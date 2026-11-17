from pathlib import Path
PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "data" / "interim" / "research"
OUT.mkdir(parents=True, exist_ok=True)
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
df = pd.read_pickle(str(OUT / "df2.pkl"))
df["rowidx"] = df.groupby("ts").cumcount()
for c in ["pct_silica_conc", "pct_iron_conc"]:
    nun = df.groupby("ts")[c].nunique()
    print(c, "distinct values per hour:")
    print(nun.value_counts().sort_index().head(10).to_string())
    varying = nun[nun > 1].index
    sub = df[df.ts.isin(varying)]
    # per varying hour: number of distinct runs
    def nruns(s):
        return 1 + int((s.values[1:] != s.values[:-1]).sum())
    r = sub.groupby("ts")[c].apply(nruns)
    print("  varying hours:", len(varying), " runs per varying hour:", r.value_counts().sort_index().head(8).to_dict())
    # where is the change: row index of first change
    def first_change(g):
        v = g.values
        idx = np.nonzero(v[1:] != v[:-1])[0]
        return int(idx[0] + 1) if len(idx) else -1
    fc = sub.groupby("ts")[c].apply(first_change)
    print("  first change row index (quantiles 0,.25,.5,.75,1):", fc.quantile([0,.25,.5,.75,1]).astype(int).tolist())
    # does the variation come from one value dominating (mode share)?
    mode_share = sub.groupby("ts")[c].apply(lambda g: g.value_counts(normalize=True).iloc[0])
    print("  modal value share in varying hours: median=%.4f min=%.4f" % (mode_share.median(), mode_share.min()))
    # do varying hours contain the hour-after value? check value ranges within hour
    rng = sub.groupby("ts")[c].agg(lambda g: g.max() - g.min())
    print("  within-hour range: median=%.4f max=%.4f" % (rng.median(), rng.max()))
# Example
ex = nun[nun > 1].index[0]
e = df[df.ts == ex][["rowidx", "pct_silica_conc", "pct_iron_conc"]]
ch = e[(e.pct_silica_conc != e.pct_silica_conc.shift()) | (e.pct_iron_conc != e.pct_iron_conc.shift())]
print("\nexample hour", ex, "change points (rowidx, values):")
print(ch.to_string(index=False))
