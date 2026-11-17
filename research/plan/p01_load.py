"""Planner check, step 1: stream the ARFF and stop at the first row dated 2017-07-31 or later.

No row of the purge day 2017-07-31 or of the test months (2017-08-01 to 2017-09-09) is parsed or kept in memory.
Writes the pre-test rows and the hourly table to this scratch directory (outside every repository).
Usage: python -I p01_load.py <arff_path> <out_dir>
"""
import csv
import hashlib
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

COLS = [
    "date", "pct_iron_feed", "pct_silica_feed", "starch_flow", "amina_flow", "ore_pulp_flow",
    "ore_pulp_ph", "ore_pulp_density",
    "air_flow_01", "air_flow_02", "air_flow_03", "air_flow_04", "air_flow_05", "air_flow_06", "air_flow_07",
    "level_01", "level_02", "level_03", "level_04", "level_05", "level_06", "level_07",
    "pct_iron_conc", "pct_silica_conc",
]
CUTOFF = "2017-07-31 00:00:00"


def main(arff: str, out: str) -> None:
    out_dir = Path(out)
    t0 = time.perf_counter()
    h = hashlib.sha256()
    with open(arff, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    t_hash = time.perf_counter() - t0
    print(f"sha256={h.hexdigest()} seconds={t_hash:.2f}")

    t0 = time.perf_counter()
    rows = []
    prev = ""
    monotone = True
    with open(arff, "r", encoding="utf-8", newline="") as fh:
        for line in fh:
            if line.strip().upper() == "@DATA":
                break
        reader = csv.reader(fh, quotechar="'", delimiter=",")
        for rec in reader:
            if not rec:
                continue
            if rec[0] >= CUTOFF:
                break
            if rec[0] < prev:
                monotone = False
            prev = rec[0]
            rows.append(rec)
    t_parse = time.perf_counter() - t0
    df = pd.DataFrame(rows, columns=COLS)
    df["ts"] = pd.to_datetime(df.pop("date"), format="%Y-%m-%d %H:%M:%S")
    for c in COLS[1:]:
        df[c] = df[c].str.replace(",", ".", regex=False).astype(float)
    t_all = time.perf_counter() - t0
    print(f"pre-test rows={len(df)} hours={df.ts.nunique()} first={df.ts.min()} last={df.ts.max()} "
          f"monotone={monotone} parse_s={t_parse:.2f} parse_and_convert_s={t_all:.2f}")
    df["row_in_hour"] = df.groupby("ts").cumcount()
    df.to_pickle(out_dir / "pretest_rows.pkl")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
