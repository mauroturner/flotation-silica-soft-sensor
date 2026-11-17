# Hour-level baselines and first look. Pre-test window only (ts < 2017-07-31). Test months never loaded.
import os, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import r2_score, mean_absolute_error, mean_squared_error
from sklearn.inspection import partial_dependence
from scipy.stats import spearmanr
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "interim", "research"); os.makedirs(OUT, exist_ok=True)
df = pd.read_pickle(f"{OUT}/df2.pkl")
df = df[df.ts < pd.Timestamp("2017-07-31")].copy()
sensors = ["starch_flow","amina_flow","ore_pulp_flow","ore_pulp_ph","ore_pulp_density"] + [f"air_flow_0{i}" for i in range(1,8)] + [f"level_0{i}" for i in range(1,8)]
g = df.groupby("ts")
agg = pd.concat({"mean": g[sensors].mean(), "std": g[sensors].std(), "last": g[sensors].last()}, axis=1)
agg.columns = [f"{s}_{k}" for k, s in agg.columns]
lab_first = g[["pct_silica_conc", "pct_iron_conc", "pct_silica_feed", "pct_iron_feed"]].first()
full = pd.date_range(df.ts.min(), df.ts.max(), freq="h")
H = agg.join(lab_first).reindex(full)
H.index.name = "ts"
y = H["pct_silica_conc"]
TR0, TR1 = pd.Timestamp("2017-03-10 01:00"), pd.Timestamp("2017-05-31 23:00")
VA0, VA1 = pd.Timestamp("2017-06-02 00:00"), pd.Timestamp("2017-07-30 23:00")
tr_mask = (H.index >= TR0) & (H.index <= TR1)
va_mask = (H.index >= VA0) & (H.index <= VA1)
print("pre-test hours on grid:", len(H), " missing hours:", int(H.sylabel if False else H.isna().all(axis=1).sum()))
print("train hours with target:", int(y[tr_mask].notna().sum()), " validation hours with target:", int(y[va_mask].notna().sum()), " validation days:", H.index[va_mask].normalize().nunique())
# ---- target profile on pre-test window
yy = y[(H.index < pd.Timestamp("2017-07-31"))].dropna()
print("\nPRE-TEST target pct_silica_conc n=%d mean=%.4f std=%.4f min=%.2f max=%.2f" % (len(yy), yy.mean(), yy.std(), yy.min(), yy.max()))
print("quantiles 1,5,25,50,75,95,99:", np.round(yy.quantile([.01,.05,.25,.5,.75,.95,.99]).values, 3).tolist(), " skew=%.3f" % yy.skew())
yfull = y.copy()
def acf(s, L):
    a = s.values[:-L]; b = s.values[L:]; m = ~np.isnan(a) & ~np.isnan(b)
    return np.corrcoef(a[m], b[m])[0,1], int(m.sum())
print("PRE-TEST ACF:", {L: round(acf(yfull, L)[0], 4) for L in [1,2,3,6,12,24]})
x = H["pct_iron_conc"]; m = x.notna() & yfull.notna()
print("PRE-TEST corr(pct_iron_conc, pct_silica_conc) pearson=%.4f" % np.corrcoef(x[m], yfull[m])[0,1])
# ---- lags (known past lab values only)
ylag = {k: y.shift(k) for k in [1,2,3,6,12,24]}
flag = {f"{c}_lag{k}": H[c].shift(k) for c in ["pct_silica_feed","pct_iron_feed"] for k in [1,2,3]}
yff = y.ffill()
pers = {d: yff.shift(d) for d in [1,2,3]}
roll = {k: yff.shift(1).rolling(k, min_periods=1).mean() for k in [3,6,12,24]}
lab_feats = pd.DataFrame({f"y_lag{k}": ylag[k] for k in [1,2,3,6,12,24]}).join(pd.DataFrame(flag))
sens_cols = [c for c in H.columns if c.endswith(("_mean","_std","_last"))]
assert len(sens_cols) == 57, len(sens_cols)
X_sens = H[sens_cols]
X_full = X_sens.join(lab_feats)
# evaluation set: validation hours with target and every baseline available
ev = va_mask & y.notna() & pers[3].notna() & roll[24].notna()
def metrics(p, mask):
    yt = y[mask].values; pp = np.asarray(p)[mask.values if hasattr(mask,'values') else mask]
    return mean_absolute_error(yt, pp), np.sqrt(mean_squared_error(yt, pp)), r2_score(yt, pp)
res = {}
# (a) training mean
mu = y[tr_mask].mean()
res["(a) training mean"] = np.full(len(H), mu)
# (b) persistence with lab delay d
for d in [1,2,3]:
    res[f"(b) persistence, delay d={d}"] = pers[d].values
# (c) rolling mean of last k known lab values (delay 1)
for k in [3,6,12,24]:
    res[f"(c) rolling mean last {k} known lab values (d=1)"] = roll[k].values
# (d) linear model on sensor aggregates only
tr_ok = tr_mask & y.notna() & X_sens.notna().all(axis=1)
ridge = make_pipeline(StandardScaler(), Ridge(alpha=1.0)).fit(X_sens[tr_ok], y[tr_ok])
p_ridge = np.full(len(H), np.nan); ok = X_sens.notna().all(axis=1).values
p_ridge[ok] = ridge.predict(X_sens[ok])
res["(d) linear model, 57 sensor aggregates"] = p_ridge
# first look: HGB sensors only, and HGB sensors + lagged lab
def hgb(cols, tag):
    tr_rows = tr_mask & y.notna() & X_full[cols].notna().all(axis=1)
    mdl = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=50, random_state=0)
    mdl.fit(X_full.loc[tr_rows, cols].values, y[tr_rows].values)
    okr = X_full[cols].notna().all(axis=1).values
    p = np.full(len(H), np.nan)
    p[okr] = mdl.predict(X_full.loc[okr, cols].values)
    print(f"  {tag}: trained on {int(tr_rows.sum())} hours, {len(cols)} columns")
    return mdl, p
lab_cols = list(lab_feats.columns)
print("\nFitting first-look models")
mdl_s, p_hgb_s = hgb(sens_cols, "HGB sensors only")
mdl_f, p_hgb_f = hgb(sens_cols + lab_cols, "HGB sensors + lagged lab (y lags 1-24, feed lags 1-3)")
res["(e) HGB sensors only (no lab)"] = p_hgb_s
res["(e) HGB sensors + lagged lab (first look)"] = p_hgb_f
print("\nValidation 2017-06-02..07-30 (common set n=%d hours, %d days)" % (ev.sum(), H.index[ev].normalize().nunique()))
print("%-55s %8s %8s %8s" % ("model", "MAE", "RMSE", "R2"))
for k, p in res.items():
    pp = pd.Series(p, index=H.index)
    yt = y[ev].values; pv = pp[ev].values
    print("%-55s %8.4f %8.4f %8.4f" % (k, mean_absolute_error(yt, pv), np.sqrt(mean_squared_error(yt, pv)), r2_score(yt, pv)))
# ---- day-block bootstrap of MAE difference
days = H.index[ev].normalize()
ud = pd.unique(days)
def daily_abs(p):
    e = np.abs(y[ev].values - np.asarray(p)[ev.values])
    s = pd.Series(e).groupby(np.asarray(days)).agg(["sum","count"])
    return s.loc[ud, "sum"].values, s.loc[ud, "count"].values
rng = np.random.default_rng(42)
B = 2000
def boot_diff(pa, pb):
    sa, ca = daily_abs(pa); sb, cb = daily_abs(pb)
    diffs = np.empty(B)
    for i in range(B):
        idx = rng.integers(0, len(ud), len(ud))
        diffs[i] = (sa[idx].sum()/ca[idx].sum()) - (sb[idx].sum()/cb[idx].sum())
    return np.percentile(diffs, [2.5, 50, 97.5]), (diffs < 0).mean()
def boot_mae(pa):
    sa, ca = daily_abs(pa)
    vals = np.empty(B)
    for i in range(B):
        idx = rng.integers(0, len(ud), len(ud))
        vals[i] = sa[idx].sum()/ca[idx].sum()
    return np.percentile(vals, [2.5, 97.5])
print("\nDay-block bootstrap (B=2000) of MAE")
for k in ["(b) persistence, delay d=1", "(c) rolling mean last 6 known lab values (d=1)", "(d) linear model, 57 sensor aggregates", "(e) HGB sensors only (no lab)", "(e) HGB sensors + lagged lab (first look)"]:
    lo, hi = boot_mae(res[k])
    print("  MAE 95%% CI %-50s [%.4f, %.4f]" % (k, lo, hi))
for a, b in [("(e) HGB sensors + lagged lab (first look)", "(b) persistence, delay d=1"),
             ("(e) HGB sensors + lagged lab (first look)", "(b) persistence, delay d=2"),
             ("(e) HGB sensors + lagged lab (first look)", "(c) rolling mean last 6 known lab values (d=1)"),
             ("(e) HGB sensors + lagged lab (first look)", "(d) linear model, 57 sensor aggregates")]:
    ci, pneg = boot_diff(res[a], res[b])
    print("  MAE diff [%s] - [%s]: median=%.4f CI95=[%.4f, %.4f]  P(diff<0)=%.3f" % (a[:30], b[:30], ci[1], ci[0], ci[2], pneg))
# save predictions for later
pd.DataFrame({k: v for k, v in res.items()}, index=H.index).to_pickle(f"{OUT}/val_preds.pkl")
pd.Series(y.values, index=H.index).to_pickle(f"{OUT}/y_pre.pkl")
import pickle
pickle.dump({"mdl_f": mdl_f, "mdl_s": mdl_s, "X_full_cols": sens_cols + lab_cols}, open(f"{OUT}/models.pkl","wb"))
X_full.to_pickle(f"{OUT}/X_full.pkl")
