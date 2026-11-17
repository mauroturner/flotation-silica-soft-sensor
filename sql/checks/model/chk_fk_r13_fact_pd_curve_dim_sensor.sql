-- R13: every fact_pd_curve[sensor_key] is a dim_sensor[sensor_key] (AC25). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.sensor_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_pd_curve AS f
WHERE f.sensor_key IS NULL OR f.sensor_key NOT IN (SELECT sensor_key FROM star_dim_sensor)
GROUP BY f.sensor_key;
