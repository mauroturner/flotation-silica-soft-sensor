-- The core of the warehouse (plan, section 5; D24): the deliveries, the rows and the hours they brought, the aggregates of each hour, the runs and
-- the results of the validation. Every table is created only if it does not exist: applying the schema again keeps the data. The estimates and
-- the evaluation tables come with the model (003_model.sql, U10); stg_hours is rebuilt by sql/staging/stg_hours.sql for each instant.
-- Instants are text 'YYYY-MM-DD HH:MM:SS' (the hour of a row on the clock of the file, no zone), which sorts as time does. A row of a sensor holds
-- no laboratory value (D04): only lab_hours holds the four values of the first row of an hour.

CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('launch', 'daily', 'close')),
    first_hour TEXT,                   -- null for the close, which holds no hour
    last_hour TEXT,
    as_of TEXT NOT NULL,
    rows INTEGER NOT NULL CHECK (rows >= 0),
    hours INTEGER NOT NULL CHECK (hours >= 0),
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('published', 'loaded', 'rejected')),
    run_key TEXT
);

CREATE TABLE IF NOT EXISTS raw_rows (
    row_id INTEGER PRIMARY KEY,
    delivery_id TEXT NOT NULL REFERENCES deliveries (delivery_id),
    hour TEXT NOT NULL,
    row_in_hour INTEGER NOT NULL CHECK (row_in_hour >= 1),
    starch_flow REAL NOT NULL,
    amina_flow REAL NOT NULL,
    ore_pulp_flow REAL NOT NULL,
    ore_pulp_ph REAL NOT NULL,
    ore_pulp_density REAL NOT NULL,
    air_flow_01 REAL NOT NULL,
    air_flow_02 REAL NOT NULL,
    air_flow_03 REAL NOT NULL,
    air_flow_04 REAL NOT NULL,
    air_flow_05 REAL NOT NULL,
    air_flow_06 REAL NOT NULL,
    air_flow_07 REAL NOT NULL,
    level_01 REAL NOT NULL,
    level_02 REAL NOT NULL,
    level_03 REAL NOT NULL,
    level_04 REAL NOT NULL,
    level_05 REAL NOT NULL,
    level_06 REAL NOT NULL,
    level_07 REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS raw_rows_by_hour ON raw_rows (hour, row_in_hour);

-- One analysis per hour: the first row's laboratory values, how fresh it is (D05), the hours since each feed last changed and the instant it
-- arrives (available_at = hour + latency_hours, D06), which is the only thing that says when a value could be used.
CREATE TABLE IF NOT EXISTS lab_hours (
    hour TEXT PRIMARY KEY,
    delivery_id TEXT NOT NULL REFERENCES deliveries (delivery_id),
    rows INTEGER NOT NULL CHECK (rows >= 1),
    is_partial INTEGER NOT NULL CHECK (is_partial IN (0, 1)),
    silica_pct REAL NOT NULL,
    iron_conc_pct REAL NOT NULL,
    feed_silica_pct REAL NOT NULL,
    feed_iron_pct REAL NOT NULL,
    lab_state TEXT NOT NULL CHECK (lab_state IN ('fresh', 'interpolated', 'held')),
    feed_silica_age_h REAL NOT NULL,
    feed_iron_age_h REAL NOT NULL,
    available_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS lab_hours_by_arrival ON lab_hours (available_at);

-- Mean, sample standard deviation (null with one row) and last value of each sensor over the rows of the hour.
CREATE TABLE IF NOT EXISTS hour_aggregates (
    hour TEXT PRIMARY KEY REFERENCES lab_hours (hour),
    rows INTEGER NOT NULL CHECK (rows >= 1),
    starch_flow_mean REAL,
    starch_flow_std REAL,
    starch_flow_last REAL,
    amina_flow_mean REAL,
    amina_flow_std REAL,
    amina_flow_last REAL,
    ore_pulp_flow_mean REAL,
    ore_pulp_flow_std REAL,
    ore_pulp_flow_last REAL,
    ore_pulp_ph_mean REAL,
    ore_pulp_ph_std REAL,
    ore_pulp_ph_last REAL,
    ore_pulp_density_mean REAL,
    ore_pulp_density_std REAL,
    ore_pulp_density_last REAL,
    air_flow_01_mean REAL,
    air_flow_01_std REAL,
    air_flow_01_last REAL,
    air_flow_02_mean REAL,
    air_flow_02_std REAL,
    air_flow_02_last REAL,
    air_flow_03_mean REAL,
    air_flow_03_std REAL,
    air_flow_03_last REAL,
    air_flow_04_mean REAL,
    air_flow_04_std REAL,
    air_flow_04_last REAL,
    air_flow_05_mean REAL,
    air_flow_05_std REAL,
    air_flow_05_last REAL,
    air_flow_06_mean REAL,
    air_flow_06_std REAL,
    air_flow_06_last REAL,
    air_flow_07_mean REAL,
    air_flow_07_std REAL,
    air_flow_07_last REAL,
    level_01_mean REAL,
    level_01_std REAL,
    level_01_last REAL,
    level_02_mean REAL,
    level_02_std REAL,
    level_02_last REAL,
    level_03_mean REAL,
    level_03_std REAL,
    level_03_last REAL,
    level_04_mean REAL,
    level_04_std REAL,
    level_04_last REAL,
    level_05_mean REAL,
    level_05_std REAL,
    level_05_last REAL,
    level_06_mean REAL,
    level_06_std REAL,
    level_06_last REAL,
    level_07_mean REAL,
    level_07_std REAL,
    level_07_last REAL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_key TEXT PRIMARY KEY,
    started_at TEXT,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'ok', 'failed', 'rejected', 'no_delivery')),
    delivery_id TEXT,
    as_of TEXT,
    source_sha256 TEXT,
    rows_delivery INTEGER,
    estimates_issued INTEGER,
    estimates_missing INTEGER,
    peak_working_set_mb REAL,
    peak_commit_mb REAL,
    memory_counter TEXT,
    message TEXT
);

CREATE TABLE IF NOT EXISTS validation_results (
    run_key TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    name_es TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('blocking', 'warning', 'info')),
    scope TEXT NOT NULL CHECK (scope IN ('source', 'delivery', 'hours', 'model')),
    aggregation TEXT NOT NULL CHECK (aggregation IN ('source', 'per_run', 'latest')),
    passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
    rows_affected INTEGER NOT NULL,
    hours_affected INTEGER NOT NULL,
    examples_json TEXT NOT NULL,       -- hours and row ids: never a value measured in the plant
    PRIMARY KEY (run_key, rule_id)
);
