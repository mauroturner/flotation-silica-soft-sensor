-- The model, what it said and when (plan, section 5; D21, D22, D24): the registry of the frozen models and the estimates, each issued once.
-- model_registry, estimates and method_estimates are insert-only: the triggers refuse, in the database itself and whoever writes, an update, a delete and
-- a second insert of a key that is already there (INSERT OR REPLACE and an upsert included: the trigger of the insert fires before the conflict is
-- resolved), so a model that was frozen or an estimate that was issued cannot be rebuilt (item 1 of the risks of the plan). The tracking and the tables of
-- the evaluation are derived and come with their own units. Instants are text 'YYYY-MM-DD HH:MM:SS'.

CREATE TABLE IF NOT EXISTS model_registry (
    model_version TEXT PRIMARY KEY,
    trained_as_of TEXT NOT NULL,
    artifact_path TEXT NOT NULL,         -- the file name inside [paths] models_dir, never a path of this machine
    artifact_sha256 TEXT NOT NULL CHECK (length(artifact_sha256) = 64),
    config_sha256 TEXT NOT NULL CHECK (length(config_sha256) = 64),
    models_json TEXT NOT NULL,           -- by horizon: family, set, target, leaf size, half-width, B* and its k
    selection_json TEXT NOT NULL,        -- the error on V1 of every candidate, by horizon (D14)
    valid_predictions_sha256 TEXT NOT NULL CHECK (length(valid_predictions_sha256) = 64)
);

-- One row per (hour of the target, horizon): the estimate with its range, the persistence and B*, or the reason there is none (a row without numbers).
-- issue_at is the instant it was said: the target hour minus the horizon plus one hour (D07). The range holds the estimate (M04).
CREATE TABLE IF NOT EXISTS estimates (
    target_hour TEXT NOT NULL,
    horizon INTEGER NOT NULL CHECK (horizon >= 0),
    issue_at TEXT NOT NULL,
    run_key TEXT NOT NULL,
    model_version TEXT NOT NULL REFERENCES model_registry (model_version),
    status TEXT NOT NULL CHECK (status IN ('ok', 'missing_inputs')),
    reason TEXT,
    estimate REAL,
    low REAL,
    high REAL,
    persistence REAL,
    b_star REAL,
    b_star_method TEXT CHECK (b_star_method IN ('b1_persistence', 'b2_rolling')),
    block TEXT NOT NULL CHECK (block IN ('train', 'purge_1', 'valid_v1', 'purge_v', 'valid_v2', 'purge_2', 'test', 'outside')),
    is_censored INTEGER NOT NULL CHECK (is_censored IN (0, 1)),
    PRIMARY KEY (target_hour, horizon),
    CHECK (issue_at = datetime(target_hour, printf('%+d hours', 1 - horizon))),
    CHECK (
        (status = 'ok' AND reason IS NULL AND estimate IS NOT NULL AND low IS NOT NULL AND high IS NOT NULL AND persistence IS NOT NULL AND b_star IS NOT NULL
            AND b_star_method IS NOT NULL AND low <= estimate AND estimate <= high)
        OR (status = 'missing_inputs' AND reason IS NOT NULL AND estimate IS NULL AND low IS NULL AND high IS NULL AND persistence IS NULL AND b_star IS NULL
            AND b_star_method IS NULL)
    )
);

-- What every method said for the same hour and horizon, for the comparison of the evaluation (RF16): only for an estimate that has numbers.
CREATE TABLE IF NOT EXISTS method_estimates (
    target_hour TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('model', 'b0_train_mean', 'b1_persistence', 'b2_rolling', 'b3_ridge_sensors', 'best_sensors_only', 'best_lab_only',
                                           'best_with_sensors')),
    estimate REAL NOT NULL,
    PRIMARY KEY (target_hour, horizon, method),
    FOREIGN KEY (target_hour, horizon) REFERENCES estimates (target_hour, horizon)
);

CREATE TRIGGER IF NOT EXISTS model_registry_no_update BEFORE UPDATE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry es de solo inserción: una versión del modelo registrada no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS model_registry_no_delete BEFORE DELETE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry es de solo inserción: una versión del modelo registrada no se borra'); END;

CREATE TRIGGER IF NOT EXISTS model_registry_no_second_insert BEFORE INSERT ON model_registry
WHEN EXISTS (SELECT 1 FROM model_registry WHERE model_version = NEW.model_version)
BEGIN SELECT RAISE(ABORT, 'model_registry es de solo inserción: esa versión del modelo ya está registrada'); END;

CREATE TRIGGER IF NOT EXISTS estimates_no_update BEFORE UPDATE ON estimates
BEGIN SELECT RAISE(ABORT, 'estimates es de solo inserción: una estimación emitida no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS estimates_no_delete BEFORE DELETE ON estimates
BEGIN SELECT RAISE(ABORT, 'estimates es de solo inserción: una estimación emitida no se borra'); END;

CREATE TRIGGER IF NOT EXISTS estimates_no_second_insert BEFORE INSERT ON estimates
WHEN EXISTS (SELECT 1 FROM estimates WHERE target_hour = NEW.target_hour AND horizon = NEW.horizon)
BEGIN SELECT RAISE(ABORT, 'estimates es de solo inserción: esa estimación ya se emitió'); END;

CREATE TRIGGER IF NOT EXISTS method_estimates_no_update BEFORE UPDATE ON method_estimates
BEGIN SELECT RAISE(ABORT, 'method_estimates es de solo inserción: lo que dijo un método no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS method_estimates_no_delete BEFORE DELETE ON method_estimates
BEGIN SELECT RAISE(ABORT, 'method_estimates es de solo inserción: lo que dijo un método no se borra'); END;

CREATE TRIGGER IF NOT EXISTS method_estimates_no_second_insert BEFORE INSERT ON method_estimates
WHEN EXISTS (SELECT 1 FROM method_estimates WHERE target_hour = NEW.target_hour AND horizon = NEW.horizon AND method = NEW.method)
BEGIN SELECT RAISE(ABORT, 'method_estimates es de solo inserción: lo que dijo ese método ya se guardó'); END;
