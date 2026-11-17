-- The 19 sensors of the plant (plan, section 19; R11 to R13), from ``ref_sensor``.
DROP TABLE IF EXISTS star_dim_sensor;

CREATE TABLE star_dim_sensor AS
SELECT sensor_key, "column", name_es, group_es, unit_es FROM ref_sensor ORDER BY sort_order;
