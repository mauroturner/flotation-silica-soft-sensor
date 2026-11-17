"""Planner check, step 2: hourly lab table, holds and ramps, on the pre-test rows only (before 2017-07-31).

Usage: python -I p02_structure.py <scratch_dir>
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = ["pct_silica_conc", "pct_iron_conc", "pct_silica_feed", "pct_iron_feed"]
BLOCKS = {
    "train": ("2017-03-10 01:00", "2017-05-31 23:00"),
    "purge_1": ("2017-06-01 00:00", "2017-06-01 23:00"),
    "valid_v1": ("2017-06-02 00:00", "2017-06-30 23:00"),
    "purge_v": ("2017-07-01 00:00", "2017-07-01 23:00"),
    "valid_v2": ("2017-07-02 00:00", "2017-07-30 23:00"),
}


def block_of(ts: pd.DatetimeIndex) -> pd.Series:
    b = pd.Series("none", index=ts)
    for name, (a, z) in BLOCKS.items():
        b[(ts >= pd.Timestamp(a)) & (ts <= pd.Timestamp(z))] = name
    return b


def main(scratch: str) -> None:
    d = Path(scratch)
    df = pd.read_pickle(d / "pretest_rows.pkl")
    g = df.groupby("ts")
    first = g[LAB].first()
    nuniq = g["pct_silica_conc"].nunique()
    nrows = g.size()
    grid = pd.date_range(df.ts.min(), df.ts.max(), freq="h")
    H = first.reindex(grid)
    H["rows"] = nrows.reindex(grid)
    H["ramp"] = (nuniq.reindex(grid) > 1)
    H["block"] = block_of(grid).values
    print("hours on grid", len(H), "with data", int(H.rows.notna().sum()))
    print("hours with data per block:", H[H.rows.notna()].groupby("block").size().to_dict())
    print("ramp hours per block:", H[H.ramp].groupby("block").size().to_dict())

    # per-row slope within each ramp hour, and whether the line continues across consecutive ramp hours
    ramp_ts = H.index[H.ramp]
    slopes = {}
    for ts in ramp_ts:
        v = df.loc[df.ts == ts, "pct_silica_conc"].values
        slopes[ts] = (v[-1] - v[0]) / (len(v) - 1)
    runs = []
    cur = []
    for ts in ramp_ts:
        if cur and ts - cur[-1] == pd.Timedelta(hours=1):
            cur.append(ts)
        else:
            if cur:
                runs.append(cur)
            cur = [ts]
    if cur:
        runs.append(cur)
    same_slope_pairs = 0
    pairs = 0
    collinear_inner = 0
    inner = 0
    for r in runs:
        for a, b in zip(r[:-1], r[1:]):
            pairs += 1
            sa, sb = slopes[a], slopes[b]
            if abs(sa - sb) <= 1e-9 + 1e-6 * max(abs(sa), abs(sb)):
                same_slope_pairs += 1
        if len(r) >= 2:
            start = H.loc[r[0], "pct_silica_conc"]
            end_ts = r[-1] + pd.Timedelta(hours=1)
            end = H.loc[end_ts, "pct_silica_conc"] if end_ts in H.index else np.nan
            n = len(r)
            for i, ts in enumerate(r[1:], start=1):
                inner += 1
                expect = start + (end - start) * i / n
                if np.isfinite(expect) and abs(H.loc[ts, "pct_silica_conc"] - expect) < 1e-6:
                    collinear_inner += 1
    lens = pd.Series([len(r) for r in runs])
    print(f"ramp runs={len(runs)} length median={lens.median()} max={lens.max()} runs_len1={int((lens == 1).sum())}")
    print(f"consecutive ramp-hour pairs={pairs} with equal per-row slope={same_slope_pairs}")
    print(f"inner hours of runs (>=2)={inner} whose first value lies on the run's straight line={collinear_inner}")
    rows_per_hour = 180
    hourly_step = {ts: slopes[ts] * rows_per_hour for ts in ramp_ts}
    # does the within-hour ramp end at the next hour's first value? (research s04 says yes)

    # holds: identical first value in consecutive observed hours
    for col in ["pct_silica_conc", "pct_silica_feed"]:
        s = H[col]
        same = (s == s.shift(1)) & s.notna() & s.shift(1).notna()
        both = s.notna() & s.shift(1).notna()
        for blk in ["train", "valid_v1", "valid_v2"]:
            m = (H.block == blk)
            print(f"{col} {blk}: consecutive pairs={int((both & m).sum())} identical={int((same & m).sum())} "
                  f"share={((same & m).sum() / max((both & m).sum(), 1)):.3f}")
        # run lengths of identical values (observed hours only)
        key = (s != s.shift(1)).cumsum()
        rl = s.groupby(key).size()[s.groupby(key).first().notna()]
        print(f"{col} run lengths of identical hourly values: median={rl.median()} p90={rl.quantile(.9)} max={rl.max()} "
              f"runs>=3h={int((rl >= 3).sum())} hours_in_runs>=3h={int(rl[rl >= 3].sum())}")
    # non-ramp hours whose value equals the previous hour (holds without a ramp)
    s = H["pct_silica_conc"]
    hold = (s == s.shift(1)) & s.notna()
    print("target holds by block (value equals previous hour):", H[hold].groupby("block").size().to_dict())
    # stuck sensors: air_flow_04/05 constant within hour, per block
    for c in ["air_flow_04", "air_flow_05"]:
        nu = g[c].nunique().reindex(grid)
        print(f"{c} constant within hour per block:", H[(nu == 1)].groupby("block").size().to_dict())
    H.to_pickle(d / "hourly_lab.pkl")


if __name__ == "__main__":
    main(sys.argv[1])
