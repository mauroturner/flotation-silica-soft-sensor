-- R02: every fact_hour_lab[hour_key] is a dim_hour[hour_key] (AC25). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.hour_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_hour_lab AS f
WHERE f.hour_key IS NULL OR f.hour_key NOT IN (SELECT hour_key FROM star_dim_hour)
GROUP BY f.hour_key;
