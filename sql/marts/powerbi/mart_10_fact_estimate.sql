-- Every estimate issued by :as_of, once (plan, section 19; R03, R05 and R14), with the analysis and the errors that ``track`` joined when the analysis had arrived: until then
-- ``actual`` and the errors are empty. The persistence and B* are the numbers of the estimate, not recomputed.
DROP TABLE IF EXISTS star_fact_estimate;

CREATE TABLE star_fact_estimate AS
SELECT CAST(strftime('%Y%m%d%H', e.target_hour) AS INTEGER) AS hour_key, e.horizon AS horizon_key, e.model_version || '-h' || e.horizon AS model_key, e.issue_at, e.status,
       e.estimate, e.low, e.high, e.persistence, e.b_star, t.actual, t.abs_error, t.abs_error_persistence, t.abs_error_b_star, t.covered, e.is_censored, e.run_key
FROM estimates AS e
LEFT JOIN tracking AS t ON t.target_hour = e.target_hour AND t.horizon = e.horizon
WHERE e.issue_at <= :as_of
ORDER BY e.target_hour, e.horizon;
