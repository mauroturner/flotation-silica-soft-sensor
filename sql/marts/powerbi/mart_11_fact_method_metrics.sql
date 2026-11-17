-- The figures of each method by block and horizon (plan, section 19; R06 and R09): the metrics of ``eval_metrics`` side by side. B* is not a row of its own (``b_star`` is the same
-- numbers as the rule it is): the row of the rule that is B* of the horizon carries ``is_b_star``. The interval against B* is the model's, in the test.
DROP TABLE IF EXISTS star_fact_method_metrics;

CREATE TABLE star_fact_method_metrics AS
WITH m AS (
    SELECT scope, horizon, method, seal_state,
           MAX(CASE WHEN metric = 'mae' THEN value END) AS mae, MAX(CASE WHEN metric = 'rmse' THEN value END) AS rmse, MAX(CASE WHEN metric = 'bias' THEN value END) AS bias,
           MAX(CASE WHEN metric = 'hours' THEN value END) AS hours, MAX(CASE WHEN metric = 'coverage' THEN value END) AS coverage
    FROM eval_metrics
    WHERE method <> 'b_star'
    GROUP BY scope, horizon, method, seal_state
)
SELECT m.scope, m.horizon AS horizon_key, m.method AS method_key, m.mae, m.rmse, m.bias, CAST(m.hours AS INTEGER) AS hours, m.coverage,
       CASE WHEN m.method = r.b_star THEN 1 ELSE 0 END AS is_b_star,
       CASE WHEN m.method = 'model' AND m.scope = 'test' THEN b.ci_low END AS ci_low_vs_b_star,
       CASE WHEN m.method = 'model' AND m.scope = 'test' THEN b.ci_high END AS ci_high_vs_b_star,
       m.seal_state
FROM m
LEFT JOIN ref_model AS r ON r.horizon_key = m.horizon
LEFT JOIN eval_bootstrap AS b ON b.comparison = 'model_vs_b_star.h' || m.horizon AND b.seal_state = m.seal_state
ORDER BY m.scope, m.horizon, m.method, m.seal_state;
