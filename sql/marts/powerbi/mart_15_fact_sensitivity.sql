-- The sensitivities of the sensors (plan, section 19; R12; D20), as an association of the model and never a cause: the label says it. ``pd_range`` is the range of the estimate along the
-- partial dependence curve of the launch (empty for a sensor that did not pass the gate, which has no curve); ``test_sign_kept`` is the sign check of the test (empty before it).
DROP TABLE IF EXISTS star_fact_sensitivity;

CREATE TABLE star_fact_sensitivity AS
SELECT s.sensor AS sensor_key, s.importance_v1, s.importance_v2, s.rho_min, s.rho_max, s.sign_stable,
       (SELECT MAX(c.estimate) - MIN(c.estimate) FROM eval_pd_curve AS c WHERE c.sensor = s.sensor AND c.scope = 'launch' AND c.seal_state = s.seal_state) AS pd_range,
       s.passes, t.kept_sign AS test_sign_kept, CASE WHEN s.passes = 1 THEN :association_es ELSE :no_association_es END AS label_es
FROM eval_sensitivity AS s
JOIN ref_shown AS r ON r.table_name = 'eval_sensitivity' AND r.seal_state = s.seal_state
LEFT JOIN eval_sensitivity_test AS t ON t.sensor = s.sensor AND t.seal_state = s.seal_state
ORDER BY s.sensor;
