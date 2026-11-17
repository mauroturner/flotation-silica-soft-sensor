"""Planner check, step 4: fresh measurements, baselines and candidates per horizon, on training and validation only.

Reads only the scratch pickles of p01/p02 (rows before 2017-07-31). Usage: python -I p04_models.py <scratch_dir>
Blocks (by target hour): train 2017-03-10 01:00..05-31 23:00; V1 06-02..06-30; V2 07-02..07-30 (purges 06-01, 07-01).
Issue instant for target hour T and horizon H: the end of hour T-H. Lab of sample hour k is known from k + L (L = 2 h).
"""
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.inspection import partial_dependence
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")
D = Path(sys.argv[1])
rows = pd.read_pickle(D / "pretest_rows.pkl")
H = pd.read_pickle(D / "hourly_lab.pkl")
SENSORS = ["starch_flow", "amina_flow", "ore_pulp_flow", "ore_pulp_ph", "ore_pulp_density"] + \
    [f"air_flow_0{i}" for i in range(1, 8)] + [f"level_0{i}" for i in range(1, 8)]
g = rows.groupby("ts")
agg = pd.concat({"mean": g[SENSORS].mean(), "std": g[SENSORS].std(), "last": g[SENSORS].last()}, axis=1)
agg.columns = [f"{s}_{k}" for k, s in agg.columns]
agg = agg.reindex(H.index)
SENS_COLS = list(agg.columns)

y = H["pct_silica_conc"]
prev_ramp = H["ramp"].shift(1, fill_value=False).astype(bool)
interp = H["ramp"] & prev_ramp                      # inner hours of a ramp run: value lies on the run's line
held = (y == y.shift(1)) & y.notna() & ~interp      # same value as the previous hour: no new measurement
fresh = y.notna() & ~interp & ~held
y_fresh = y.where(fresh)
blk = H["block"]
for b in ["train", "valid_v1", "valid_v2"]:
    m = blk == b
    print(f"{b}: hours with value={int((y.notna() & m).sum())} interpolated={int((interp & m).sum())} "
          f"held={int((held & m).sum())} fresh={int((fresh & m).sum())}")

# lab features from the sequence of fresh measurements known at instant t (sample hours k <= t - L)
idx = H.index
pos = np.arange(len(idx))
fresh_pos = pos[fresh.values]
fresh_val = y.values[fresh.values]
feed_s = H["pct_silica_feed"].values
feed_i = H["pct_iron_feed"].values
feed_change = np.r_[True, (H["pct_silica_feed"].values[1:] != H["pct_silica_feed"].values[:-1])
                    | (H["pct_iron_feed"].values[1:] != H["pct_iron_feed"].values[:-1])]


def lab_features(L: int, Hh: int) -> pd.DataFrame:
    """Row per target hour T: features known at the end of hour T - Hh."""
    out = np.full((len(idx), 8), np.nan)
    for p in range(len(idx)):
        kmax = p - Hh + 1 - L          # last sample hour known (positions are hours)
        j = np.searchsorted(fresh_pos, kmax, side="right")
        if j < 6:
            continue
        vals = fresh_val[:j]
        out[p, 0] = vals[-1]
        out[p, 1] = vals[-2]
        out[p, 2] = vals[-3]
        out[p, 3] = vals[-6:].mean()
        out[p, 4] = vals[-24:].mean() if j >= 24 else np.nan
        out[p, 5] = kmax - fresh_pos[j - 1]
        # feed: last value known at kmax and hours since it changed
        if kmax >= 0 and not np.isnan(feed_s[kmax]):
            out[p, 6] = feed_s[kmax]
            out[p, 7] = feed_i[kmax]
    cols = ["lab_last1", "lab_last2", "lab_last3", "lab_mean6", "lab_mean24", "lab_age_h", "feed_silica", "feed_iron"]
    return pd.DataFrame(out, index=idx, columns=cols)


def sens_features(Hh: int) -> pd.DataFrame:
    return agg.shift(Hh)            # sensors of hour T - Hh


TRAIN, V1, V2 = (blk == "train"), (blk == "valid_v1"), (blk == "valid_v2")


def mae(a, b):
    return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))


def day_boot(err_a, err_b, days, B=2000, seed=0):
    ud = np.unique(days)
    rng = np.random.default_rng(seed)
    sa = pd.Series(err_a).groupby(days).agg(["sum", "count"]).loc[ud]
    sb = pd.Series(err_b).groupby(days).agg(["sum", "count"]).loc[ud]
    out = np.empty(B)
    for i in range(B):
        k = rng.integers(0, len(ud), len(ud))
        out[i] = sa["sum"].values[k].sum() / sa["count"].values[k].sum() - sb["sum"].values[k].sum() / sb["count"].values[k].sum()
    return np.percentile(out, [2.5, 97.5])


def candidates():
    out = []
    for msl in (20, 50):
        out.append(("hgb", msl, lambda msl=msl: HistGradientBoostingRegressor(
            learning_rate=0.05, max_iter=300, max_leaf_nodes=15, min_samples_leaf=msl, l2_regularization=1.0,
            early_stopping=False, random_state=0)))
    for msl in (5, 20):
        out.append(("rf", msl, lambda msl=msl: RandomForestRegressor(
            n_estimators=300, max_features=0.33, min_samples_leaf=msl, n_jobs=1, random_state=0)))
    return out


# ---- p05: the configuration chosen on V1 (by p04) refit on train + V1, evaluated on V2 (planner check, pre-test only)
CHOSEN = {0: ("rf", "fSLF", "change", 20), 1: ("rf", "fSL", "level", 20), 2: ("rf", "fSLF", "level", 20)}
for Hh, (fam, fs, target, msl) in CHOSEN.items():
    LAB = lab_features(2, Hh)
    S = sens_features(Hh)
    X_all = S.join(LAB)
    cols = SENS_COLS + ["lab_last1", "lab_last2", "lab_last3", "lab_mean6", "lab_mean24", "lab_age_h"]
    if fs == "fSLF":
        cols = cols + ["feed_silica", "feed_iron"]
    ok = y_fresh.notna() & LAB["lab_mean24"].notna() & S.notna().all(axis=1)
    m2 = V2 & ok
    make = [c[2] for c in candidates() if c[0] == fam and c[1] == msl][0]
    yv2 = y_fresh[m2].values
    days = np.asarray(idx[m2].normalize())
    pers = LAB["lab_last1"][m2].values
    mean3 = ((LAB["lab_last1"] + LAB["lab_last2"] + LAB["lab_last3"]) / 3)[m2].values
    for label, trm in (("train only", TRAIN & ok), ("train + V1", (TRAIN | V1) & ok)):
        ytr = y_fresh[trm] - (LAB["lab_last1"][trm] if target == "change" else 0)
        mdl = make().fit(X_all.loc[trm, cols].values, ytr.values)
        p = mdl.predict(X_all.loc[m2, cols].values) + (LAB["lab_last1"][m2].values if target == "change" else 0)
        e = np.abs(yv2 - p)
        ci_p = day_boot(e, np.abs(yv2 - pers), days)
        ci_m = day_boot(e, np.abs(yv2 - mean3), days)
        print(f"H={Hh} {fam}_{fs}_{target}_msl{msl} fit on {label}: rows={int(trm.sum())} V2 MAE={e.mean():.4f} bias={np.mean(p - yv2):+.4f} "
              f"| persistence {np.abs(yv2 - pers).mean():.4f} CI(model-pers) [{ci_p[0]:+.4f}, {ci_p[1]:+.4f}] "
              f"| mean3 {np.abs(yv2 - mean3).mean():.4f} CI(model-mean3) [{ci_m[0]:+.4f}, {ci_m[1]:+.4f}]")
