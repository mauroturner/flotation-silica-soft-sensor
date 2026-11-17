"""The leak, shown on purpose (D09; plan, section 16): what a random split and what the iron of the concentrate do to the validation error of the chosen model.

``leakage_table`` takes the blocks of the launch at the horizon 0 and the candidate the launch chose, and gives three rows:

* ``blocks``: the candidate fitted on the training block and measured on V2, with the error (MAE) and the R² it has when the data are cut in time: the honest figure;
* ``random_split``: the same candidate fitted on a random 80 % of the hours of the training block, V1 and V2 together (seed 0) and measured on the other 20 %: the figure
  of a random partition, which sees the neighbours of every hour it is measured on (research.md measured R² 0.565 against −0.511);
* ``iron_conc``: the same candidate with ``% Iron Concentrate`` of the target hour added to its columns, fitted on the training block and measured on V2: the variable
  the guards of ``features.build_matrix`` refuse and the trip-wire M01 would stop (correlation −0.80 with the target).

The iron is added here, past ``build_matrix``, because this module exists to show what the guards and M01 stop. It never writes to the registry or to the estimates (a
static test reads this file for that), and nothing it computes reaches the model, a threshold or a criterion.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import r2_score

from flotsilica.features import build_matrix
from flotsilica.model import BlockData, Candidate, make_estimator

SPLIT_SEED = 0
TEST_SHARE = 0.2
CHECKS_ES = {
    "blocks": "Entrenar con los bloques de entrenamiento y medir en V2, como se hace",
    "random_split": "Mezclar al azar las horas de entrenamiento, V1 y V2: 80 % para ajustar y 20 % para medir",
    "iron_conc": "Agregar el hierro del concentrado de la hora del objetivo a las columnas",
}
NOTES_ES = {
    "blocks": "La cifra honesta: el modelo no ve nada posterior al bloque que mide.",
    "random_split": "Las horas vecinas están en los dos lados de la partición: parece mejor de lo que es.",
    "iron_conc": "Mira la misma hora que el objetivo: las guardas lo rechazan por su nombre y la trampa M01 detiene un lanzamiento con un error así.",
}


def _fit_predict(candidate: Candidate, view: Any, x_train: np.ndarray, y_train: np.ndarray, base_train: np.ndarray | None, x_test: np.ndarray,
                 base_test: np.ndarray | None) -> np.ndarray:
    estimator = make_estimator(candidate, view).fit(x_train, y_train if base_train is None else y_train - base_train)
    out = np.asarray(estimator.predict(x_test), dtype="float64")
    return out if base_test is None else base_test + out


def _row(check: str, actual: np.ndarray, estimate: np.ndarray) -> dict[str, Any]:
    return {"check_id": check, "description_es": CHECKS_ES[check], "mae": float(np.mean(np.abs(estimate - actual))), "r2": float(r2_score(actual, estimate)),
            "rows": int(len(actual)), "note_es": NOTES_ES[check]}


def leakage_table(blocks: Mapping[str, BlockData], iron: pd.Series, candidate: Candidate, view: Any) -> pd.DataFrame:
    """``check_id``, ``description_es``, ``mae``, ``r2``, ``rows`` and ``note_es`` of the three checks, for the blocks of the horizon 0 (``train``, ``valid_v1`` and
    ``valid_v2``), `iron` (``% Iron Concentrate`` of each hour, indexed by hour) and the candidate the launch chose."""
    columns = list(build_matrix(blocks["train"].X, candidate.feature_set).columns)       # the columns of its set, through the guard

    def parts(name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, np.ndarray]:
        block = blocks[name]
        x = block.X[columns].to_numpy(dtype="float64")
        base = block.last1 if candidate.target == "change" else None
        return x, block.y, base, iron.reindex(block.hours).to_numpy(dtype="float64")

    (xt, yt, bt, it), (x2, y2, b2, i2) = parts("train"), parts("valid_v2")
    rows = [_row("blocks", y2, _fit_predict(candidate, view, xt, yt, bt, x2, b2))]
    pool = [parts(name) for name in ("train", "valid_v1", "valid_v2")]
    x, y = np.vstack([p[0] for p in pool]), np.concatenate([p[1] for p in pool])
    base = np.concatenate([p[2] for p in pool]) if candidate.target == "change" else None
    chosen = np.random.default_rng(SPLIT_SEED).permutation(len(y))
    cut = int(round(len(y) * (1 - TEST_SHARE)))
    fit, test = chosen[:cut], chosen[cut:]
    rows.append(_row("random_split", y[test], _fit_predict(candidate, view, x[fit], y[fit], None if base is None else base[fit], x[test], None if base is None else base[test])))
    if np.isnan(it).any() or np.isnan(i2).any():
        raise ValueError("el hierro del concentrado de una hora de entrenamiento o de V2 no está en el almacén")
    rows.append(_row("iron_conc", y2, _fit_predict(candidate, view, np.column_stack([xt, it]), yt, bt, np.column_stack([x2, i2]), b2)))
    return pd.DataFrame(rows)
