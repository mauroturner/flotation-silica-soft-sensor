"""Planner check, step 3: decimal precision of the hourly target (pre-test only). Usage: python -I p03_precision.py <scratch_dir>"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
H = pd.read_pickle(Path(sys.argv[1]) / "hourly_lab.pkl")
s = H["pct_silica_conc"].dropna()
for k in [1, 2, 3, 4, 6]:
    print(f"share of hourly values with at most {k} decimals: {np.mean(np.isclose(s * 10**k, np.round(s * 10**k), atol=1e-7)):.3f}")
print("distinct hourly values:", s.nunique(), "of", len(s))
non_ramp = H[~H.ramp & H.pct_silica_conc.notna()]["pct_silica_conc"]
print("non-ramp hours:", len(non_ramp), "share with at most 2 decimals:", round(float(np.mean(np.isclose(non_ramp * 100, np.round(non_ramp * 100), atol=1e-7))), 3))
