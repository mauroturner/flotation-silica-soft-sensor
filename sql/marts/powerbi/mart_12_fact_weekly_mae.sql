-- The error by week of the test (plan, section 19; R07 and R10): the weeks of 7 days from the first day of the test, numbered from 1. B* is the rule it is: when it is the persistence
-- its row would repeat the persistence's, so only a B* that is the rolling mean gets its own row.
DROP TABLE IF EXISTS star_fact_weekly_mae;

CREATE TABLE star_fact_weekly_mae AS
SELECT CAST((julianday(w.week) - julianday(date(:test_first))) / 7 AS INTEGER) + 1 AS test_week, w.horizon AS horizon_key,
       CASE WHEN w.method = 'b_star' THEN r.b_star ELSE w.method END AS method_key, w.mae, w.hours, w.seal_state
FROM eval_weekly AS w
LEFT JOIN ref_model AS r ON r.horizon_key = w.horizon
WHERE NOT (w.method = 'b_star' AND r.b_star = 'b1_persistence')
ORDER BY test_week, w.horizon, method_key, w.seal_state;
