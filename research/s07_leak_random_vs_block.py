# Random row split vs time-block split on the PRE-TEST window only (test months 2017-08-01..09-09 never loaded here).
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import r2_score, mean_absolute_error
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "interim", "research"); os.makedirs(OUT, exist_ok=True)
df = pd.read_pickle(f"{OUT}/df2.pkl")
df = df[df.ts <= pd.Timestamp("2017-07-31 00:00:00")].copy()
sensors = ["starch_flow","amina_flow","ore_pulp_flow","ore_pulp_ph","ore_pulp_density"] + [f"air_flow_0{i}" for i in range(1,8)] + [f"level_0{i}" for i in range(1,8)]
X = df[sensors].astype("float32").values
y = df["pct_silica_conc"].values
hour = df["ts"].values
print("pre-test rows:", len(df), "hours:", df.ts.nunique(), "sensors:", len(sensors))
rng = np.random.default_rng(0)
mask = rng.random(len(df)) < 0.8
def fit_eval(tr, te, tag):
    t0 = time.time()
    m = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.1, random_state=0)
    m.fit(X[tr], y[tr])
    p = m.predict(X[te])
    shared = np.isin(hour[te], np.unique(hour[tr]))
    print(f"{tag}: train={tr.sum()} test={te.sum()} R2={r2_score(y[te], p):.4f} MAE={mean_absolute_error(y[te], p):.4f} "
          f"test rows whose hour also appears in train={shared.mean()*100:.2f}% time={time.time()-t0:.1f}s")
fit_eval(mask, ~mask, "RANDOM row split 80/20 (pre-test)")
tr = df.ts.values < np.datetime64("2017-06-01")
te = (df.ts.values >= np.datetime64("2017-06-02")) & (df.ts.values < np.datetime64("2017-07-31"))
fit_eval(tr, te, "TIME-BLOCK split: train to 2017-05-31, purge 06-01, test 06-02..07-30")
