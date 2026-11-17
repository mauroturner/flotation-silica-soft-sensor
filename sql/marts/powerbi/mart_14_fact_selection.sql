-- The candidates of each horizon with their error in V1 (plan, section 19; R08), in the state a reader shows (``ref_shown``: the sealed rows when there are any).
DROP TABLE IF EXISTS star_fact_selection;

CREATE TABLE star_fact_selection AS
SELECT s.horizon AS horizon_key, s.family, s.feature_set, s.target, s.min_samples_leaf, s.mae_v1, s.chosen
FROM eval_selection AS s
JOIN ref_shown AS r ON r.table_name = 'eval_selection' AND r.seal_state = s.seal_state
ORDER BY s.horizon, s.family, s.feature_set, s.target, s.min_samples_leaf;
