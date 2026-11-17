import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import r2_score, mean_absolute_error
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "interim", "research"); os.makedirs(OUT, exist_ok=True)
df = pd.read_pickle(f"{OUT}/df2.pkl")
df = df[df.ts < pd.Timestamp("2017-07-31")].copy()
sensors = ["starch_flow","amina_flow","ore_pulp_flow","ore_pulp_ph","ore_pulp_density"] + [f"air_flow_0{i}" for i in range(1,8)] + [f"level_0{i}" for i in range(1,8)]
feeds = ["pct_iron_feed","pct_silica_feed"]
y = df["pct_silica_conc"].values
rng = np.random.default_rng(0)
mask = rng.random(len(df)) < 0.8
tr_t = df.ts.values < np.datetime64("2017-06-01")
te_t = (df.ts.values >= np.datetime64("2017-06-02")) & (df.ts.values < np.datetime64("2017-07-31"))
def run(cols, split, tag):
    X = df[cols].astype("float32").values
    if split == "random":
        tr, te = mask, ~mask
    else:
        tr, te = tr_t, te_t
    m = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.1, random_state=0).fit(X[tr], y[tr])
    p = m.predict(X[te])
    print(f"{tag:45s} R2={r2_score(y[te], p):.4f} MAE={mean_absolute_error(y[te], p):.4f}")
run(sensors + feeds, "random", "RANDOM split, 19 sensors + 2 feed lab")
run(sensors + feeds, "block", "TIME-BLOCK split, 19 sensors + 2 feed lab")
