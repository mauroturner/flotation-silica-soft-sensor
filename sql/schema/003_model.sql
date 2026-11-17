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

-- The evaluation (plan, sections 5 and 16; D16, D18, D19): what the launch and the test measured, with the state of the seal each number was made under.
-- ``seal_state`` is 'sealed' (the sealed configuration: the triggers below refuse to change, remove or write again a sealed row) or 'post_seal' (another
-- configuration, M05: replaced when the run repeats and never in place of a sealed row). ``scope`` is the block the figures are of: the validation blocks come from
-- the launch and are labelled as such wherever they are shown, the test from the one evaluation.

CREATE TABLE IF NOT EXISTS eval_selection (
    horizon INTEGER NOT NULL,
    candidate TEXT NOT NULL,
    family TEXT NOT NULL,
    feature_set TEXT NOT NULL,
    target TEXT NOT NULL,
    min_samples_leaf INTEGER NOT NULL,
    mae_v1 REAL NOT NULL,
    chosen INTEGER NOT NULL CHECK (chosen IN (0, 1)),
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    run_key TEXT NOT NULL,
    PRIMARY KEY (horizon, candidate, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_baselines (
    horizon INTEGER NOT NULL,
    method TEXT NOT NULL,
    k INTEGER,
    mae_v1 REAL NOT NULL,
    cohort_v1 INTEGER NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    run_key TEXT NOT NULL,
    PRIMARY KEY (horizon, method, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_metrics (
    scope TEXT NOT NULL CHECK (scope IN ('valid_v1', 'valid_v2', 'test')),
    horizon INTEGER NOT NULL,
    method TEXT NOT NULL,
    metric TEXT NOT NULL CHECK (metric IN ('hours', 'mae', 'rmse', 'bias', 'coverage')),
    value REAL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    run_key TEXT NOT NULL,
    PRIMARY KEY (scope, horizon, method, metric, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_bootstrap (
    comparison TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    difference REAL NOT NULL,
    ci_low REAL NOT NULL,
    ci_high REAL NOT NULL,
    resamples INTEGER NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    run_key TEXT NOT NULL,
    PRIMARY KEY (comparison, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_criteria (
    criterion_id TEXT NOT NULL,
    name_es TEXT NOT NULL,
    value REAL,
    baseline_value REAL,
    ci_low REAL,
    ci_high REAL,
    threshold_es TEXT NOT NULL,
    passed INTEGER CHECK (passed IN (0, 1)),
    seen_by_research TEXT NOT NULL,
    seen_by_planner TEXT NOT NULL,
    verdict_es TEXT NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    run_key TEXT NOT NULL,
    PRIMARY KEY (criterion_id, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_weekly (
    week TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    method TEXT NOT NULL,
    mae REAL NOT NULL,
    hours INTEGER NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    run_key TEXT NOT NULL,
    PRIMARY KEY (week, horizon, method, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_variants (
    variant TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    method TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    run_key TEXT NOT NULL,
    PRIMARY KEY (variant, horizon, method, metric, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_leakage (
    check_id TEXT NOT NULL,
    description_es TEXT NOT NULL,
    mae REAL NOT NULL,
    r2 REAL NOT NULL,
    rows INTEGER NOT NULL,
    note_es TEXT NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    run_key TEXT NOT NULL,
    PRIMARY KEY (check_id, seal_state)
);

CREATE TRIGGER IF NOT EXISTS eval_selection_sealed_no_update BEFORE UPDATE ON eval_selection WHEN OLD.seal_state = 'sealed' OR NEW.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_selection: una fila sellada es de solo inserción: no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_selection_sealed_no_delete BEFORE DELETE ON eval_selection WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_selection: una fila sellada es de solo inserción: no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_selection_sealed_no_second_insert BEFORE INSERT ON eval_selection
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_selection WHERE seal_state = 'sealed' AND horizon = NEW.horizon AND candidate = NEW.candidate)
BEGIN SELECT RAISE(ABORT, 'eval_selection: una fila sellada es de solo inserción: ya está escrita'); END;

CREATE TRIGGER IF NOT EXISTS eval_baselines_sealed_no_update BEFORE UPDATE ON eval_baselines WHEN OLD.seal_state = 'sealed' OR NEW.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_baselines: una fila sellada es de solo inserción: no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_baselines_sealed_no_delete BEFORE DELETE ON eval_baselines WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_baselines: una fila sellada es de solo inserción: no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_baselines_sealed_no_second_insert BEFORE INSERT ON eval_baselines
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_baselines WHERE seal_state = 'sealed' AND horizon = NEW.horizon AND method = NEW.method)
BEGIN SELECT RAISE(ABORT, 'eval_baselines: una fila sellada es de solo inserción: ya está escrita'); END;

CREATE TRIGGER IF NOT EXISTS eval_metrics_sealed_no_update BEFORE UPDATE ON eval_metrics WHEN OLD.seal_state = 'sealed' OR NEW.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_metrics: una fila sellada es de solo inserción: no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_metrics_sealed_no_delete BEFORE DELETE ON eval_metrics WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_metrics: una fila sellada es de solo inserción: no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_metrics_sealed_no_second_insert BEFORE INSERT ON eval_metrics
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_metrics WHERE seal_state = 'sealed' AND scope = NEW.scope AND horizon = NEW.horizon AND method = NEW.method AND metric = NEW.metric)
BEGIN SELECT RAISE(ABORT, 'eval_metrics: una fila sellada es de solo inserción: ya está escrita'); END;

CREATE TRIGGER IF NOT EXISTS eval_bootstrap_sealed_no_update BEFORE UPDATE ON eval_bootstrap WHEN OLD.seal_state = 'sealed' OR NEW.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_bootstrap: una fila sellada es de solo inserción: no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_bootstrap_sealed_no_delete BEFORE DELETE ON eval_bootstrap WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_bootstrap: una fila sellada es de solo inserción: no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_bootstrap_sealed_no_second_insert BEFORE INSERT ON eval_bootstrap
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_bootstrap WHERE seal_state = 'sealed' AND comparison = NEW.comparison)
BEGIN SELECT RAISE(ABORT, 'eval_bootstrap: una fila sellada es de solo inserción: ya está escrita'); END;

CREATE TRIGGER IF NOT EXISTS eval_criteria_sealed_no_update BEFORE UPDATE ON eval_criteria WHEN OLD.seal_state = 'sealed' OR NEW.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_criteria: una fila sellada es de solo inserción: no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_criteria_sealed_no_delete BEFORE DELETE ON eval_criteria WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_criteria: una fila sellada es de solo inserción: no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_criteria_sealed_no_second_insert BEFORE INSERT ON eval_criteria
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_criteria WHERE seal_state = 'sealed' AND criterion_id = NEW.criterion_id)
BEGIN SELECT RAISE(ABORT, 'eval_criteria: una fila sellada es de solo inserción: ya está escrita'); END;

CREATE TRIGGER IF NOT EXISTS eval_weekly_sealed_no_update BEFORE UPDATE ON eval_weekly WHEN OLD.seal_state = 'sealed' OR NEW.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_weekly: una fila sellada es de solo inserción: no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_weekly_sealed_no_delete BEFORE DELETE ON eval_weekly WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_weekly: una fila sellada es de solo inserción: no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_weekly_sealed_no_second_insert BEFORE INSERT ON eval_weekly
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_weekly WHERE seal_state = 'sealed' AND week = NEW.week AND horizon = NEW.horizon AND method = NEW.method)
BEGIN SELECT RAISE(ABORT, 'eval_weekly: una fila sellada es de solo inserción: ya está escrita'); END;

CREATE TRIGGER IF NOT EXISTS eval_variants_sealed_no_update BEFORE UPDATE ON eval_variants WHEN OLD.seal_state = 'sealed' OR NEW.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_variants: una fila sellada es de solo inserción: no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_variants_sealed_no_delete BEFORE DELETE ON eval_variants WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_variants: una fila sellada es de solo inserción: no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_variants_sealed_no_second_insert BEFORE INSERT ON eval_variants
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_variants WHERE seal_state = 'sealed' AND variant = NEW.variant AND horizon = NEW.horizon AND method = NEW.method AND metric = NEW.metric)
BEGIN SELECT RAISE(ABORT, 'eval_variants: una fila sellada es de solo inserción: ya está escrita'); END;

CREATE TRIGGER IF NOT EXISTS eval_leakage_sealed_no_update BEFORE UPDATE ON eval_leakage WHEN OLD.seal_state = 'sealed' OR NEW.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_leakage: una fila sellada es de solo inserción: no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_leakage_sealed_no_delete BEFORE DELETE ON eval_leakage WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_leakage: una fila sellada es de solo inserción: no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_leakage_sealed_no_second_insert BEFORE INSERT ON eval_leakage
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_leakage WHERE seal_state = 'sealed' AND check_id = NEW.check_id)
BEGIN SELECT RAISE(ABORT, 'eval_leakage: una fila sellada es de solo inserción: ya está escrita'); END;

-- The sensitivities (D20; RF20): every sensor with its importances in V1 and V2, the range of the Spearman correlations of its partial dependence and whether it passes the gate of the
-- launch (``eval_sensitivity``); whether each sensor that passed keeps its sign over the hours of the test (``eval_sensitivity_test``, C09); and the curves of the sensors that passed.
-- All of them are associations of the model, with the same rule for the sealed rows as the tables above.

CREATE TABLE IF NOT EXISTS eval_sensitivity (
    sensor TEXT NOT NULL,
    importance_v1 REAL NOT NULL,
    importance_v2 REAL NOT NULL,
    rho_min REAL,
    rho_max REAL,
    sign_stable INTEGER NOT NULL CHECK (sign_stable IN (0, 1)),
    passes INTEGER NOT NULL CHECK (passes IN (0, 1)),
    sign INTEGER NOT NULL CHECK (sign IN (-1, 0, 1)),
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    run_key TEXT NOT NULL,
    PRIMARY KEY (sensor, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_sensitivity_test (
    sensor TEXT NOT NULL,
    sealed_sign INTEGER NOT NULL CHECK (sealed_sign IN (-1, 1)),
    rho_test REAL NOT NULL,
    kept_sign INTEGER NOT NULL CHECK (kept_sign IN (0, 1)),
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    run_key TEXT NOT NULL,
    PRIMARY KEY (sensor, seal_state)
);

CREATE TABLE IF NOT EXISTS eval_pd_curve (
    sensor TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('launch', 'test')),
    point INTEGER NOT NULL,
    value REAL NOT NULL,
    estimate REAL NOT NULL,
    seal_state TEXT NOT NULL CHECK (seal_state IN ('sealed', 'post_seal')),
    run_key TEXT NOT NULL,
    PRIMARY KEY (sensor, scope, point, seal_state)
);

CREATE TRIGGER IF NOT EXISTS eval_sensitivity_sealed_no_update BEFORE UPDATE ON eval_sensitivity WHEN OLD.seal_state = 'sealed' OR NEW.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_sensitivity: una fila sellada es de solo inserción: no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_sensitivity_sealed_no_delete BEFORE DELETE ON eval_sensitivity WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_sensitivity: una fila sellada es de solo inserción: no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_sensitivity_sealed_no_second_insert BEFORE INSERT ON eval_sensitivity
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_sensitivity WHERE seal_state = 'sealed' AND sensor = NEW.sensor)
BEGIN SELECT RAISE(ABORT, 'eval_sensitivity: una fila sellada es de solo inserción: ya está escrita'); END;

CREATE TRIGGER IF NOT EXISTS eval_sensitivity_test_sealed_no_update BEFORE UPDATE ON eval_sensitivity_test WHEN OLD.seal_state = 'sealed' OR NEW.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_sensitivity_test: una fila sellada es de solo inserción: no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_sensitivity_test_sealed_no_delete BEFORE DELETE ON eval_sensitivity_test WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_sensitivity_test: una fila sellada es de solo inserción: no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_sensitivity_test_sealed_no_second_insert BEFORE INSERT ON eval_sensitivity_test
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_sensitivity_test WHERE seal_state = 'sealed' AND sensor = NEW.sensor)
BEGIN SELECT RAISE(ABORT, 'eval_sensitivity_test: una fila sellada es de solo inserción: ya está escrita'); END;

CREATE TRIGGER IF NOT EXISTS eval_pd_curve_sealed_no_update BEFORE UPDATE ON eval_pd_curve WHEN OLD.seal_state = 'sealed' OR NEW.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_pd_curve: una fila sellada es de solo inserción: no se cambia'); END;

CREATE TRIGGER IF NOT EXISTS eval_pd_curve_sealed_no_delete BEFORE DELETE ON eval_pd_curve WHEN OLD.seal_state = 'sealed'
BEGIN SELECT RAISE(ABORT, 'eval_pd_curve: una fila sellada es de solo inserción: no se borra'); END;

CREATE TRIGGER IF NOT EXISTS eval_pd_curve_sealed_no_second_insert BEFORE INSERT ON eval_pd_curve
WHEN NEW.seal_state = 'sealed' AND EXISTS (SELECT 1 FROM eval_pd_curve WHERE seal_state = 'sealed' AND sensor = NEW.sensor AND scope = NEW.scope AND point = NEW.point)
BEGIN SELECT RAISE(ABORT, 'eval_pd_curve: una fila sellada es de solo inserción: ya está escrita'); END;
