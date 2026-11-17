-- The runs of the flow (plan, section 19; R15): the columns of ``pipeline_runs``. The closing of a run rewrites this table alone (plan, section 3, step 11).
DROP TABLE IF EXISTS star_dim_pipeline_run;

CREATE TABLE star_dim_pipeline_run AS
SELECT run_key, started_at, finished_at, status, delivery_id, as_of, source_sha256, rows_delivery, estimates_issued, estimates_missing, peak_working_set_mb, peak_commit_mb,
       memory_counter, message
FROM pipeline_runs ORDER BY run_key;
