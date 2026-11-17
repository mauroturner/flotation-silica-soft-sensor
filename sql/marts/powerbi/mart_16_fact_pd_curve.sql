-- The partial dependence curves of the launch, of the sensors that passed the gate (plan, section 19; R13): the estimate of the model along the values of the sensor.
DROP TABLE IF EXISTS star_fact_pd_curve;

CREATE TABLE star_fact_pd_curve AS
SELECT c.sensor AS sensor_key, c.point, c.value AS grid_value, c.estimate AS mean_estimate
FROM eval_pd_curve AS c
JOIN ref_shown AS r ON r.table_name = 'eval_pd_curve' AND r.seal_state = c.seal_state
WHERE c.scope = 'launch'
ORDER BY c.sensor, c.point;
