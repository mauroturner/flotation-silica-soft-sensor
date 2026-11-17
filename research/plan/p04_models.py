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


results = {}
fit_times = {"hgb": [], "rf": []}
for Hh in (0, 1, 2):
    LAB = lab_features(2, Hh)
    S = sens_features(Hh)
    X_all = S.join(LAB)
    sets = {
        "fS": SENS_COLS,
        "fL": ["lab_last1", "lab_last2", "lab_last3", "lab_mean6", "lab_mean24", "lab_age_h"],
    }
    sets["fSL"] = SENS_COLS + sets["fL"]
    sets["fSLF"] = sets["fSL"] + ["feed_silica", "feed_iron"]
    tgt = y_fresh
    ok_base = tgt.notna() & LAB["lab_mean24"].notna()
    ev = {name: m & ok_base & S.notna().all(axis=1) for name, m in (("V1", V1), ("V2", V2))}
    tr = TRAIN & ok_base & S.notna().all(axis=1)
    print(f"\n=== H={Hh} (L=2): train rows={int(tr.sum())} V1={int(ev['V1'].sum())} V2={int(ev['V2'].sum())}")
    row = {}
    mu = tgt[tr].mean()
    for vb in ("V1", "V2"):
        m = ev[vb]
        row[("B0_train_mean", vb)] = mae(tgt[m], mu)
        row[("B1_persistence", vb)] = mae(tgt[m], LAB["lab_last1"][m])
        row[("B2_mean6", vb)] = mae(tgt[m], LAB["lab_mean6"][m])
        # rolling mean of the last k fresh values, k in 3, 12, 24
        row[("B2_mean3", vb)] = mae(tgt[m], (LAB["lab_last1"][m] + LAB["lab_last2"][m] + LAB["lab_last3"][m]) / 3)
        row[("B2_mean24", vb)] = mae(tgt[m], LAB["lab_mean24"][m])
    ridge = make_pipeline(StandardScaler(), Ridge(alpha=1.0)).fit(S[tr], tgt[tr])
    for vb in ("V1", "V2"):
        row[("B3_ridge_sensors", vb)] = mae(tgt[ev[vb]], ridge.predict(S[ev[vb]]))
    preds = {}
    for fs, cols in sets.items():
        for target in (("level",) if fs == "fS" else ("level", "change")):
            ytr = tgt[tr] - (LAB["lab_last1"][tr] if target == "change" else 0)
            for fam, msl, make in candidates():
                t0 = time.perf_counter()
                mdl = make().fit(X_all.loc[tr, cols].values, ytr.values)
                fit_times[fam].append(time.perf_counter() - t0)
                name = f"{fam}_{fs}_{target}_msl{msl}"
                for vb in ("V1", "V2"):
                    m = ev[vb]
                    p = mdl.predict(X_all.loc[m, cols].values) + (LAB["lab_last1"][m].values if target == "change" else 0)
                    preds[(name, vb)] = p
                    row[(name, vb)] = mae(tgt[m], p)
                preds[(name, "model")] = (mdl, cols, target)
    tab = pd.Series(row).unstack()
    tab = tab.sort_values("V1")
    print(tab.round(4).to_string())
    best = tab.index[[not i.startswith("B") for i in tab.index]][0]
    best_s = [i for i in tab.index if ("_fSL_" in i or "_fSLF_" in i)][0]
    best_l = [i for i in tab.index if "_fL_" in i][0]
    best_fs = [i for i in tab.index if "_fS_" in i][0]
    pers_v2 = LAB["lab_last1"][ev["V2"]].values
    days = np.asarray(idx[ev["V2"]].normalize())
    yv2 = tgt[ev["V2"]].values
    for lab_, nm in (("best on V1", best), ("best sensor model on V1", best_s), ("best lab-only on V1", best_l)):
        ci = day_boot(np.abs(yv2 - preds[(nm, "V2")]), np.abs(yv2 - pers_v2), days)
        print(f"  {lab_}: {nm} V2 MAE={tab.loc[nm, 'V2']:.4f}; minus persistence on V2: CI95 [{ci[0]:.4f}, {ci[1]:.4f}]")
    ci = day_boot(np.abs(yv2 - preds[(best_s, "V2")]), np.abs(yv2 - preds[(best_l, "V2")]), days)
    print(f"  sensors add (best sensor - best lab-only) on V2: CI95 [{ci[0]:.4f}, {ci[1]:.4f}]")
    mu_err = np.abs(yv2 - mu)
    ci = day_boot(np.abs(yv2 - preds[(best_fs, "V2")]), mu_err, days)
    print(f"  sensors only {best_fs} minus training mean on V2: MAE {tab.loc[best_fs, 'V2']:.4f} vs {tab.loc['B0_train_mean', 'V2']:.4f}; CI95 [{ci[0]:.4f}, {ci[1]:.4f}]")
    # bias on V2 of the best
    print(f"  bias on V2 (mean pred - actual): best={np.mean(preds[(best, 'V2')] - yv2):+.4f} persistence={np.mean(pers_v2 - yv2):+.4f}")
    # split conformal: 80 % interval half-width from V1 absolute residuals of the best, coverage on V2
    r1 = np.abs(tgt[ev["V1"]].values - preds[(best, "V1")])
    n1 = len(r1)
    q = np.quantile(r1, min(1.0, np.ceil((n1 + 1) * 0.8) / n1), method="higher")
    cov = np.mean(np.abs(yv2 - preds[(best, "V2")]) <= q)
    print(f"  conformal 80 %: half-width from V1 = {q:.4f}; coverage on V2 = {cov:.3f}")
    results[Hh] = (tab, best, best_s, preds, X_all, ev, tr, LAB, S, sets)

print("\nfit seconds: hgb median %.2f max %.2f; rf median %.2f max %.2f" % (
    np.median(fit_times["hgb"]), np.max(fit_times["hgb"]), np.median(fit_times["rf"]), np.max(fit_times["rf"])))

# latency sensitivity at H = 0: persistence and the best H0 configuration refit with L = 3, 4
tab0, best0 = results[0][0], results[0][1]
fam, fs, target, msl = best0.split("_")[0], best0.split("_")[1], best0.split("_")[2], int(best0.split("msl")[1])
for L in (2, 3, 4):
    LAB = lab_features(L, 0)
    S = sens_features(0)
    X_all = S.join(LAB)
    cols = results[0][9][fs]
    ok = y_fresh.notna() & LAB["lab_mean24"].notna() & S.notna().all(axis=1)
    tr = TRAIN & ok
    m = (V1 | V2) & ok
    make = [c[2] for c in candidates() if c[0] == fam and c[1] == msl][0]
    ytr = y_fresh[tr] - (LAB["lab_last1"][tr] if target == "change" else 0)
    mdl = make().fit(X_all.loc[tr, cols].values, ytr.values)
    p = mdl.predict(X_all.loc[m, cols].values) + (LAB["lab_last1"][m].values if target == "change" else 0)
    print(f"latency L={L} h (d={L-1}): validation V1+V2 n={int(m.sum())} persistence MAE={mae(y_fresh[m], LAB['lab_last1'][m]):.4f} {best0} MAE={mae(y_fresh[m], p):.4f}")

# all-hours persistence (as in research.md, value of every hour with clock lag 1) for comparison
allm = (V1 | V2 | (blk == "purge_v")) & y.notna() & y.shift(1).notna()
vm = (blk.isin(["valid_v1", "purge_v", "valid_v2"])) & y.notna() & y.ffill().shift(1).notna()
print("research-style persistence (every hour, clock lag 1, 06-02..07-30):", round(mae(y[vm], y.ffill().shift(1)[vm]), 4), "n=", int(vm.sum()))
fm = vm & fresh
print("same, only fresh target hours:", round(mae(y[fm], y.ffill().shift(1)[fm]), 4), "n=", int(fm.sum()))

# sensitivity gate at H = 0 on the best sensor-using candidate
tab, best, best_s, preds, X_all, ev, tr, LAB, S, sets = results[0]
mdl, cols, target = preds[(best_s, "model")]
fam, msl = best_s.split("_")[0], int(best_s.split("msl")[1])
make = [c[2] for c in candidates() if c[0] == fam and c[1] == msl][0]
rng = np.random.default_rng(0)


def predict(model, X, m):
    return model.predict(X) + (LAB["lab_last1"][m].values if target == "change" else 0)


imp = {}
for vb in ("V1", "V2"):
    m = ev[vb]
    X = X_all.loc[m, cols].values.copy()
    base = mae(y_fresh[m], predict(mdl, X, m))
    for s in SENSORS:
        ci = [cols.index(f"{s}_{k}") for k in ("mean", "std", "last")]
        inc = []
        for r in range(5):
            Xp = X.copy()
            perm = rng.permutation(len(Xp))
            Xp[:, ci] = Xp[perm][:, ci]
            inc.append(mae(y_fresh[m], predict(mdl, Xp, m)) - base)
        imp[(s, vb)] = (np.mean(inc), np.std(inc))
# partial-dependence direction across 5 day-block bootstrap refits of the same configuration
tr_days = np.asarray(X_all.index[tr].normalize())
ud = np.unique(tr_days)
signs = {s: [] for s in SENSORS}
Xtr = X_all.loc[tr, cols]
ytr = (y_fresh[tr] - (LAB["lab_last1"][tr] if target == "change" else 0)).values
for b in range(6):
    if b == 0:
        sel = np.ones(len(Xtr), bool)
        model_b = mdl
    else:
        pick = rng.choice(ud, len(ud), replace=True)
        w = pd.Series(tr_days).map(pd.Series(pick).value_counts()).fillna(0).values
        sel = w > 0
        model_b = make().fit(np.repeat(Xtr.values[sel], w[sel].astype(int), axis=0), np.repeat(ytr[sel], w[sel].astype(int)))
    Xv = X_all.loc[ev["V1"] | ev["V2"], cols].values
    for s in SENSORS:
        j = cols.index(f"{s}_mean")
        grid = np.quantile(Xv[:, j], np.linspace(0.05, 0.95, 15))
        pdv = []
        for gv in grid:
            Xg = Xv.copy()
            Xg[:, j] = gv
            pdv.append(model_b.predict(Xg).mean())
        rho = spearmanr(grid, pdv).correlation
        signs[s].append((rho, float(np.max(pdv) - np.min(pdv))))
passing = []
print(f"\nsensitivity gate on {best_s} (H=0): grouped permutation increase of MAE (mean of 5) on V1 and V2, PD Spearman over 6 fits")
for s in SENSORS:
    i1, i2 = imp[(s, "V1")][0], imp[(s, "V2")][0]
    rhos = [r for r, _ in signs[s]]
    stable_sign = all(np.sign(r) == np.sign(rhos[0]) and abs(r) >= 0.5 for r in rhos if np.isfinite(r))
    ok = i1 >= 0.01 and i2 >= 0.01 and stable_sign
    if ok:
        passing.append(s)
    print(f"  {s:17s} V1 {i1:+.4f} V2 {i2:+.4f}  rho {['%+.2f' % r for r in rhos]}  range {np.max([r for _, r in signs[s]]):.3f}  pass={ok}")
print("sensors passing the gate:", passing)
