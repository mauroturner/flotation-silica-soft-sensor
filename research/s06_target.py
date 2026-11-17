from pathlib import Path
PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "data" / "interim" / "research"
OUT.mkdir(parents=True, exist_ok=True)
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from scipy import stats
df = pd.read_pickle(str(OUT / "df2.pkl"))
# hour-level series: value at row 0 of each hour (the hour's lab anchor, see s04/s05)
hr = df.groupby("ts").first().drop(columns=[], errors="ignore")
full = pd.date_range(hr.index.min(), hr.index.max(), freq="h")
hr = hr.reindex(full)
hr.to_pickle(str(OUT / "hourly_first.pkl"))
y = hr["pct_silica_conc"]
yy = y.dropna()
print("TARGET pct_silica_conc, hour-level (row 0), n=%d" % len(yy))
print("mean=%.4f std=%.4f min=%.4f max=%.4f" % (yy.mean(), yy.std(), yy.min(), yy.max()))
q = yy.quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
print("quantiles 1,5,25,50,75,95,99:", np.round(q.values, 3).tolist())
print("skew=%.3f excess kurtosis=%.3f" % (stats.skew(yy), stats.kurtosis(yy)))
counts, edges = np.histogram(yy, bins=12)
print("histogram (12 bins):")
for c, a, b in zip(counts, edges[:-1], edges[1:]):
    print("  [%.2f,%.2f): %d" % (a, b, c))
def acf(s, lag):
    a = s.values[:-lag]; b = s.values[lag:]
    m = ~np.isnan(a) & ~np.isnan(b)
    return np.corrcoef(a[m], b[m])[0, 1], int(m.sum())
print("autocorrelation on full hourly grid (pairs with both observed):")
for L in [1, 2, 3, 6, 12, 24]:
    r, n = acf(y, L)
    print("  lag %2d h: r=%.4f (pairs=%d)" % (L, r, n))
# iron concentrate vs silica concentrate (same moment, hour level)
x = hr["pct_iron_conc"]
m = x.notna() & y.notna()
print("\ncorr(pct_iron_conc, pct_silica_conc) hour-level: pearson=%.4f spearman=%.4f" % (
    np.corrcoef(x[m], y[m])[0, 1], stats.spearmanr(x[m], y[m]).statistic))
print("pct_iron_conc: mean=%.3f std=%.3f min=%.3f max=%.3f" % (x.mean(), x.std(), x.min(), x.max()))
# feed run lengths (hour-level, consecutive present hours with identical value)
def runs(s):
    s = s.copy()
    present = s.notna()
    out = []
    cur_v = None; cur_len = 0
    for v, p in zip(s.values, present.values):
        if not p:
            if cur_len: out.append(cur_len)
            cur_v = None; cur_len = 0
            continue
        if cur_v is not None and v == cur_v:
            cur_len += 1
        else:
            if cur_len: out.append(cur_len)
            cur_v = v; cur_len = 1
    if cur_len: out.append(cur_len)
    return pd.Series(out)
for c in ["pct_silica_feed", "pct_iron_feed"]:
    r = runs(hr[c])
    print(f"\n{c}: runs={len(r)} median={r.median():.0f} mean={r.mean():.1f} p90={r.quantile(.9):.0f} max={r.max()}")
    print("  runs >=24h:", int((r>=24).sum()), " >=72h:", int((r>=72).sum()), " >=168h:", int((r>=168).sum()))
    print("  distinct values:", int(hr[c].nunique()), " changes between consecutive present hours:", int((hr[c].diff().abs()>0).sum()))
    print("  run length quantiles 25,50,75:", r.quantile([.25,.5,.75]).tolist())
# where are the longest runs for feed
s = hr["pct_silica_feed"]
ch = s.ne(s.shift()) & s.notna()
grp = ch.cumsum()
lens = s.groupby(grp).agg(["first", "size"])
lens = lens[lens["first"].notna()] if "first" in lens else lens
top = s.groupby(grp).apply(lambda g: (g.index[0], g.index[-1], len(g.dropna()), g.dropna().iloc[0] if g.notna().any() else np.nan)).dropna()
