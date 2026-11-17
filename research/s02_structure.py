from pathlib import Path
PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "data" / "interim" / "research"
OUT.mkdir(parents=True, exist_ok=True)
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
df = pd.read_pickle(str(OUT / "df.pkl"))
df = df.drop(columns=["_raw_date"])
print("timestamp minute/second values:", sorted(df.ts.dt.minute.unique())[:5], sorted(df.ts.dt.second.unique())[:5])
rph = df.groupby("ts").size()
print("rows per hour: n_hours=", len(rph), "min=", rph.min(), "max=", rph.max(), "mean=%.2f" % rph.mean())
vc = rph.value_counts().sort_index()
print("rows-per-hour distribution (count of hours):")
print(vc.to_string())
print("share of hours with 180 rows: %.2f%%" % (100 * (rph == 180).mean()))
print("total rows check: sum rows =", int(rph.sum()))
# within-hour constancy
lab = ["pct_iron_feed", "pct_silica_feed", "pct_iron_conc", "pct_silica_conc"]
sens = [c for c in df.columns if c not in lab + ["ts"]]
nun = df.groupby("ts")[df.columns.drop("ts")].nunique()
print("\nshare of hours where column is constant within the hour (nunique==1):")
print((nun == 1).mean().round(4).to_string())
# hourly grid and gaps
full = pd.date_range(df.ts.min(), df.ts.max(), freq="h")
print("\nexpected hours in span:", len(full), " observed:", rph.shape[0], " missing:", len(full) - rph.shape[0])
present = pd.Series(1, index=rph.index).reindex(full, fill_value=0)
miss = ~present.astype(bool)
# runs of missing hours
runs = []
start = None
for t, m in miss.items():
    if m and start is None:
        start = t; prev = t
    elif m:
        prev = t
    elif (not m) and start is not None:
        runs.append((start, prev)); start = None
if start is not None: runs.append((start, prev))
runs_df = pd.DataFrame([(a, b, int(((b - a) / pd.Timedelta("1h")) + 1)) for a, b in runs], columns=["start", "end", "hours"])
print("missing-hour runs total:", len(runs_df), " hours:", int(runs_df.hours.sum()))
print("missing runs of length 1 hour:", int((runs_df.hours == 1).sum()))
print("missing runs longer than 1 hour (gaps):")
print(runs_df[runs_df.hours > 1].to_string(index=False))
# missing hours by month
mm = miss.groupby(miss.index.to_period("M")).sum()
print("\nmissing hours per month:")
print(mm.to_string())
# consecutive-row checks for 20s sampling inside hour: check rows of one hour are unique in sensor values
s = df[df.ts == rph.index[1000]]
print("\nexample hour rows:", len(s), "unique air_flow_01 values in that hour:", s.air_flow_01.nunique())
df.to_pickle(str(OUT / "df2.pkl"))
runs_df.to_csv(str(OUT / "gaps.csv"), index=False)
