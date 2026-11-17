-- What the test says when one assumption changes (plan, section 19; C10): the error of the model and of the persistence under each variant, and for the model the interval of its
-- difference with the persistence. Informative: nothing that chooses reads it (D11).
DROP TABLE IF EXISTS star_fact_variants;

CREATE TABLE star_fact_variants AS
WITH v AS (
    SELECT variant, horizon, method, seal_state,
           MAX(CASE WHEN metric = 'mae' THEN value END) AS mae, MAX(CASE WHEN metric = 'hours' THEN value END) AS hours,
           MAX(CASE WHEN metric = 'ci_low' THEN value END) AS ci_low, MAX(CASE WHEN metric = 'ci_high' THEN value END) AS ci_high
    FROM eval_variants
    GROUP BY variant, horizon, method, seal_state
)
SELECT v.variant, COALESCE(n.variant_es, v.variant) AS variant_es, v.horizon AS horizon_key, v.method AS method_key, v.mae, CAST(v.hours AS INTEGER) AS hours,
       d.ci_low AS ci_low, d.ci_high AS ci_high
FROM v
JOIN ref_shown AS r ON r.table_name = 'eval_variants' AND r.seal_state = v.seal_state
LEFT JOIN ref_variant AS n ON n.variant = v.variant
LEFT JOIN v AS d ON d.variant = v.variant AND d.horizon = v.horizon AND d.seal_state = v.seal_state AND d.method = 'model_vs_b1_persistence' AND v.method = 'model'
WHERE v.method IN ('model', 'b1_persistence')
ORDER BY v.variant, v.horizon, v.method;
