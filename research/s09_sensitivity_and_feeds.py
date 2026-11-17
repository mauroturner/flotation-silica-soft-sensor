import os, sys, pickle, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from sklearn.inspection import partial_dependence
from scipy.stats import spearmanr
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "interim", "research"); os.makedirs(OUT, exist_ok=True)
X = pd.read_pickle(f"{OUT}/X_full.pkl")
ym = pd.read_pickle(f"{OUT}/y_pre.pkl")
M = pickle.load(open(f"{OUT}/models.pkl","rb"))
sens_cols = M["X_full_cols"][:57]; lab_cols = M["X_full_cols"][57:]
VA0, VA1 = pd.Timestamp("2017-06-02"), pd.Timestamp("2017-07-31")
va = (X.index >= VA0) & (X.index < VA1)
def grouped_perm(model, cols, tag, n_rep=5):
    Xv = X.loc[va & ym.notna().values & X[cols].notna().all(axis=1).values, cols].values
    yv = ym[va & ym.notna().values & X[cols].notna().all(axis=1).values].values
    base = np.mean(np.abs(model.predict(Xv) - yv))
    groups = {}
    for s in sorted(set(c.rsplit("_",1)[0] for c in sens_cols)):
        idx = [i for i,c in enumerate(cols) if c.startswith(s+"_") and c.rsplit("_",1)[1] in ("mean","std","last")]
        groups[s] = idx
    rng = np.random.default_rng(0)
    rows = []
    for s, idx in groups.items():
        inc = []
        for r in range(n_rep):
            Xp = Xv.copy(); perm = rng.permutation(len(Xv))
            Xp[:, idx] = Xv[perm][:, idx]
            inc.append(np.mean(np.abs(model.predict(Xp) - yv)) - base)
        rows.append((s, np.mean(inc), np.std(inc)))
    df = pd.DataFrame(rows, columns=["sensor","mae_increase","sd"]).sort_values("mae_increase", ascending=False)
    print(f"\n{tag}: n={len(Xv)} base MAE={base:.4f}; grouped permutation importance (MAE increase, mean of {n_rep})")
    print(df.head(12).round(4).to_string(index=False))
    return df
imp_s = grouped_perm(M["mdl_s"], sens_cols, "SENSORS-ONLY HGB") if False else None
import pickle as pk
mdl_s = M["mdl_s"]; mdl_f = M["mdl_f"]
imp_s = grouped_perm(mdl_s, sens_cols, "SENSORS-ONLY HGB")
imp_f = grouped_perm(mdl_f, sens_cols + lab_cols, "FULL HGB (sensors + lagged lab)")
# partial dependence on the mean aggregate of the top sensors (sensors-only model)
print("\nPartial dependence on sensor hourly mean (SENSORS-ONLY HGB), validation grid 5th-95th pct:")
Xv_s = X.loc[va, sens_cols]
rows = []
for s in ["air_flow_01","air_flow_04","starch_flow","amina_flow","ore_pulp_ph","ore_pulp_density","level_01","level_04","ore_pulp_flow"]:
    col = f"{s}_mean"; j = sens_cols.index(col)
    pdp = partial_dependence(mdl_s, Xv_s.values, features=[j], kind="average", grid_resolution=20, percentiles=(0.05,0.95))
    grid = pdp["grid_values"][0]; avg = pdp["average"][0]
    rho = spearmanr(grid, avg).statistic
    rows.append((s, round(float(avg.max()-avg.min()),4), round(float(rho),3)))
print(pd.DataFrame(rows, columns=["sensor","pd_range","spearman_grid_vs_pd"]).to_string(index=False))
print("\nPartial dependence on sensor hourly mean (FULL HGB), same grid:")
Xv_f = X.loc[va, sens_cols+lab_cols].fillna(method=None) if False else X.loc[va, sens_cols+lab_cols]
ok = Xv_f.notna().all(axis=1).values
rows = []
for s in ["air_flow_01","air_flow_04","starch_flow","amina_flow","ore_pulp_ph","ore_pulp_density","level_01","level_04"]:
    j = (sens_cols+lab_cols).index(f"{s}_mean")
    pdp = partial_dependence(mdl_f, Xv_f.values[ok], features=[j], kind="average", grid_resolution=20, percentiles=(0.05,0.95))
    grid = pdp["grid_values"][0]; avg = pdp["average"][0]
    rows.append((s, round(float(avg.max()-avg.min()),4), round(float(spearmanr(grid, avg).statistic),3)))
print(pd.DataFrame(rows, columns=["sensor","pd_range","spearman_grid_vs_pd"]).to_string(index=False))
# mean shift train vs validation
ytr = ym[(ym.index >= "2017-03-10 01:00") & (ym.index <= "2017-05-31 23:00")].dropna()
yva = ym[va].dropna()
print("\ntarget mean train=%.4f (n=%d), validation=%.4f (n=%d)" % (ytr.mean(), len(ytr), yva.mean(), len(yva)))
# feed run lengths within pre-test window (hour level, present hours)
import itertools
Hf = pd.read_pickle(f"{OUT}/hourly_first.pkl")
Hf = Hf[Hf.index < pd.Timestamp("2017-07-31")]
for c in ["pct_silica_feed","pct_iron_feed"]:
    s = Hf[c]
    grp = (s != s.shift()).cumsum()
    rl = s.groupby(grp).agg(["first","size", "count"])
    rl = rl[rl["count"] > 0]
    print(f"\n{c} pre-test: runs={len(rl)} median={rl['size'].median()} max={rl['size'].max()} runs>=24h={int((rl['size']>=24).sum())} runs>=72h={int((rl['size']>=72).sum())}")
    top = rl.sort_values("size", ascending=False).head(3)
    for gid, r in top.iterrows():
        idx = s.index[grp == gid]
        print(f"   run: {idx.min()} to {idx.max()} length={len(idx)} h value={r['first']}")
# partial hours
cnt = pd.read_pickle(f"{OUT}/df2.pkl").groupby("ts").size()
print("\nhours with fewer than 180 rows:", cnt[cnt < 180].to_dict())
# count-only test window (rows and hours, no values read)
d = pd.read_pickle(f"{OUT}/df2.pkl")
t = d[(d.ts >= pd.Timestamp("2017-08-01")) & (d.ts <= pd.Timestamp("2017-09-09 23:00"))]
print("TEST window (count only): hours=%d rows=%d" % (t.ts.nunique(), len(t)))
