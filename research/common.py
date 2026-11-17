"""Shared loader for the flotation ARFF file. Read-only parsing; never executes file content."""
from pathlib import Path
PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "data" / "interim" / "research"
OUT.mkdir(parents=True, exist_ok=True)
import sys
import pandas as pd

ARFF_PATH = str(PROJECT / "data" / "raw" / "openml-43311-quality-prediction-mining-process.arff")

COLS = [
    "date", "pct_iron_feed", "pct_silica_feed", "starch_flow", "amina_flow", "ore_pulp_flow",
    "ore_pulp_ph", "ore_pulp_density",
    "air_flow_01", "air_flow_02", "air_flow_03", "air_flow_04", "air_flow_05", "air_flow_06", "air_flow_07",
    "level_01", "level_02", "level_03", "level_04", "level_05", "level_06", "level_07",
    "pct_iron_conc", "pct_silica_conc",
]

def load_raw(path=ARFF_PATH):
    """Return the raw table with every field as text (quotechar apostrophe, data starts after @DATA)."""
    with open(path, "r", encoding="utf-8", errors="strict") as fh:
        skip = 0
        for i, line in enumerate(fh):
            if line.strip().upper() == "@DATA":
                skip = i + 1
                break
    df = pd.read_csv(path, skiprows=skip, header=None, names=COLS, quotechar="'",
                     dtype=str, keep_default_na=False, na_values=[], engine="python")
    return df

def to_float(s):
    return pd.to_numeric(s.str.replace(",", ".", regex=False), errors="coerce")

def load(path=ARFF_PATH):
    raw = load_raw(path)
    df = pd.DataFrame({"ts": pd.to_datetime(raw["date"], format="%Y-%m-%d %H:%M:%S", errors="coerce")})
    for c in COLS[1:]:
        df[c] = to_float(raw[c])
    df["_raw_date"] = raw["date"]
    return df
