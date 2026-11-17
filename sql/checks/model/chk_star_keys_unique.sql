-- The key of every table of the star model is unique and never empty (AC25): a violation is the table, the problem (a key that repeats or a key with an empty part)
-- and how many.
SELECT 'dim_date' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_dim_date GROUP BY date_key HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'dim_date', 'null', n FROM (SELECT COUNT(*) AS n FROM star_dim_date WHERE date_key IS NULL) WHERE n > 0
UNION ALL
SELECT 'dim_hour' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_dim_hour GROUP BY hour_key HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'dim_hour', 'null', n FROM (SELECT COUNT(*) AS n FROM star_dim_hour WHERE hour_key IS NULL) WHERE n > 0
UNION ALL
SELECT 'dim_horizon' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_dim_horizon GROUP BY horizon_key HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'dim_horizon', 'null', n FROM (SELECT COUNT(*) AS n FROM star_dim_horizon WHERE horizon_key IS NULL) WHERE n > 0
UNION ALL
SELECT 'dim_method' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_dim_method GROUP BY method_key HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'dim_method', 'null', n FROM (SELECT COUNT(*) AS n FROM star_dim_method WHERE method_key IS NULL) WHERE n > 0
UNION ALL
SELECT 'dim_sensor' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_dim_sensor GROUP BY sensor_key HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'dim_sensor', 'null', n FROM (SELECT COUNT(*) AS n FROM star_dim_sensor WHERE sensor_key IS NULL) WHERE n > 0
UNION ALL
SELECT 'dim_model' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_dim_model GROUP BY model_key HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'dim_model', 'null', n FROM (SELECT COUNT(*) AS n FROM star_dim_model WHERE model_key IS NULL) WHERE n > 0
UNION ALL
SELECT 'dim_pipeline_run' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_dim_pipeline_run GROUP BY run_key HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'dim_pipeline_run', 'null', n FROM (SELECT COUNT(*) AS n FROM star_dim_pipeline_run WHERE run_key IS NULL) WHERE n > 0
UNION ALL
SELECT 'fact_hour_process' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_fact_hour_process GROUP BY hour_key, sensor_key HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'fact_hour_process', 'null', n FROM (SELECT COUNT(*) AS n FROM star_fact_hour_process WHERE hour_key IS NULL OR sensor_key IS NULL) WHERE n > 0
UNION ALL
SELECT 'fact_hour_lab' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_fact_hour_lab GROUP BY hour_key HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'fact_hour_lab', 'null', n FROM (SELECT COUNT(*) AS n FROM star_fact_hour_lab WHERE hour_key IS NULL) WHERE n > 0
UNION ALL
SELECT 'fact_estimate' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_fact_estimate GROUP BY hour_key, horizon_key HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'fact_estimate', 'null', n FROM (SELECT COUNT(*) AS n FROM star_fact_estimate WHERE hour_key IS NULL OR horizon_key IS NULL) WHERE n > 0
UNION ALL
SELECT 'fact_method_metrics' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_fact_method_metrics GROUP BY scope, horizon_key, method_key, seal_state HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'fact_method_metrics', 'null', n FROM (SELECT COUNT(*) AS n FROM star_fact_method_metrics WHERE scope IS NULL OR horizon_key IS NULL OR method_key IS NULL OR seal_state IS NULL) WHERE n > 0
UNION ALL
SELECT 'fact_weekly_mae' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_fact_weekly_mae GROUP BY test_week, horizon_key, method_key, seal_state HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'fact_weekly_mae', 'null', n FROM (SELECT COUNT(*) AS n FROM star_fact_weekly_mae WHERE test_week IS NULL OR horizon_key IS NULL OR method_key IS NULL OR seal_state IS NULL) WHERE n > 0
UNION ALL
SELECT 'fact_evaluation_summary' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_fact_evaluation_summary GROUP BY criterion_id, seal_state HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'fact_evaluation_summary', 'null', n FROM (SELECT COUNT(*) AS n FROM star_fact_evaluation_summary WHERE criterion_id IS NULL OR seal_state IS NULL) WHERE n > 0
UNION ALL
SELECT 'fact_selection' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_fact_selection GROUP BY horizon_key, family, feature_set, target, min_samples_leaf HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'fact_selection', 'null', n FROM (SELECT COUNT(*) AS n FROM star_fact_selection WHERE horizon_key IS NULL OR family IS NULL OR feature_set IS NULL OR target IS NULL OR min_samples_leaf IS NULL) WHERE n > 0
UNION ALL
SELECT 'fact_sensitivity' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_fact_sensitivity GROUP BY sensor_key HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'fact_sensitivity', 'null', n FROM (SELECT COUNT(*) AS n FROM star_fact_sensitivity WHERE sensor_key IS NULL) WHERE n > 0
UNION ALL
SELECT 'fact_pd_curve' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_fact_pd_curve GROUP BY sensor_key, point HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'fact_pd_curve', 'null', n FROM (SELECT COUNT(*) AS n FROM star_fact_pd_curve WHERE sensor_key IS NULL OR point IS NULL) WHERE n > 0
UNION ALL
SELECT 'fact_variants' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_fact_variants GROUP BY variant, horizon_key, method_key HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'fact_variants', 'null', n FROM (SELECT COUNT(*) AS n FROM star_fact_variants WHERE variant IS NULL OR horizon_key IS NULL OR method_key IS NULL) WHERE n > 0
UNION ALL
SELECT 'fact_leakage' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_fact_leakage GROUP BY "check" HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'fact_leakage', 'null', n FROM (SELECT COUNT(*) AS n FROM star_fact_leakage WHERE "check" IS NULL) WHERE n > 0
UNION ALL
SELECT 'fact_data_quality' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_fact_data_quality GROUP BY date_key HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'fact_data_quality', 'null', n FROM (SELECT COUNT(*) AS n FROM star_fact_data_quality WHERE date_key IS NULL) WHERE n > 0
UNION ALL
SELECT 'fact_validation' AS star_table, 'duplicated' AS problem, n AS keys FROM (SELECT COUNT(*) AS n FROM (SELECT 1 FROM star_fact_validation GROUP BY run_key, rule_id HAVING COUNT(*) > 1)) WHERE n > 0
UNION ALL
SELECT 'fact_validation', 'null', n FROM (SELECT COUNT(*) AS n FROM star_fact_validation WHERE run_key IS NULL OR rule_id IS NULL) WHERE n > 0;
