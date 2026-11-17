-- R07: every fact_weekly_mae[horizon_key] is a dim_horizon[horizon_key] (AC25). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.horizon_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_weekly_mae AS f
WHERE f.horizon_key IS NULL OR f.horizon_key NOT IN (SELECT horizon_key FROM star_dim_horizon)
GROUP BY f.horizon_key;
