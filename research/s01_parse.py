from pathlib import Path
PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "data" / "interim" / "research"
OUT.mkdir(parents=True, exist_ok=True)
import sys
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from common import load_raw, load, COLS, ARFF_PATH

raw = load_raw(ARFF_PATH)
print("raw rows:", len(raw), "raw cols:", raw.shape[1])
print("cols match:", list(raw.columns) == COLS)
bad_ts = pd.to_datetime(raw["date"], format="%Y-%m-%d %H:%M:%S", errors="coerce").isna().sum()
print("unparseable timestamps:", int(bad_ts))
# values that are not numbers after comma->dot
df = load(ARFF_PATH)
print("NaN per column (after numeric conversion):")
print(df.isna().sum().to_string())
print("ts min/max:", df.ts.min(), df.ts.max())
print("distinct timestamps:", df.ts.nunique())
print("duplicate timestamp rows:", int(df.ts.duplicated().sum()))
df.to_pickle(str(OUT / "df.pkl"))
