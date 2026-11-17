-- The aggregates of each hour are those of its rows (V14's second line): the count and the mean of each sensor, to 1e-9 (absolute plus
-- relative). An hour with aggregates and no rows, or with rows and no aggregates, is a violation too. Each violation is the hour, what differs
-- ('rows', 'hour_without_rows', 'hour_without_aggregates' or the sensor) and the two values.
WITH stats AS (
    SELECT hour, COUNT(*) AS n,
           AVG(starch_flow) AS starch_flow_avg,
           AVG(amina_flow) AS amina_flow_avg,
           AVG(ore_pulp_flow) AS ore_pulp_flow_avg,
           AVG(ore_pulp_ph) AS ore_pulp_ph_avg,
           AVG(ore_pulp_density) AS ore_pulp_density_avg,
           AVG(air_flow_01) AS air_flow_01_avg,
           AVG(air_flow_02) AS air_flow_02_avg,
           AVG(air_flow_03) AS air_flow_03_avg,
           AVG(air_flow_04) AS air_flow_04_avg,
           AVG(air_flow_05) AS air_flow_05_avg,
           AVG(air_flow_06) AS air_flow_06_avg,
           AVG(air_flow_07) AS air_flow_07_avg,
           AVG(level_01) AS level_01_avg,
           AVG(level_02) AS level_02_avg,
           AVG(level_03) AS level_03_avg,
           AVG(level_04) AS level_04_avg,
           AVG(level_05) AS level_05_avg,
           AVG(level_06) AS level_06_avg,
           AVG(level_07) AS level_07_avg
    FROM raw_rows GROUP BY hour
)
SELECT a.hour, 'rows', a.rows, s.n FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour WHERE a.rows <> s.n
UNION ALL
SELECT a.hour, 'hour_without_rows', a.rows, NULL FROM hour_aggregates AS a WHERE a.hour NOT IN (SELECT hour FROM stats)
UNION ALL
SELECT s.hour, 'hour_without_aggregates', NULL, s.n FROM stats AS s WHERE s.hour NOT IN (SELECT hour FROM hour_aggregates)
UNION ALL
SELECT a.hour, 'starch_flow', a.starch_flow_mean, s.starch_flow_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.starch_flow_mean - s.starch_flow_avg) > 0.000000001 + 0.000000001 * ABS(s.starch_flow_avg)
UNION ALL
SELECT a.hour, 'amina_flow', a.amina_flow_mean, s.amina_flow_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.amina_flow_mean - s.amina_flow_avg) > 0.000000001 + 0.000000001 * ABS(s.amina_flow_avg)
UNION ALL
SELECT a.hour, 'ore_pulp_flow', a.ore_pulp_flow_mean, s.ore_pulp_flow_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.ore_pulp_flow_mean - s.ore_pulp_flow_avg) > 0.000000001 + 0.000000001 * ABS(s.ore_pulp_flow_avg)
UNION ALL
SELECT a.hour, 'ore_pulp_ph', a.ore_pulp_ph_mean, s.ore_pulp_ph_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.ore_pulp_ph_mean - s.ore_pulp_ph_avg) > 0.000000001 + 0.000000001 * ABS(s.ore_pulp_ph_avg)
UNION ALL
SELECT a.hour, 'ore_pulp_density', a.ore_pulp_density_mean, s.ore_pulp_density_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.ore_pulp_density_mean - s.ore_pulp_density_avg) > 0.000000001 + 0.000000001 * ABS(s.ore_pulp_density_avg)
UNION ALL
SELECT a.hour, 'air_flow_01', a.air_flow_01_mean, s.air_flow_01_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.air_flow_01_mean - s.air_flow_01_avg) > 0.000000001 + 0.000000001 * ABS(s.air_flow_01_avg)
UNION ALL
SELECT a.hour, 'air_flow_02', a.air_flow_02_mean, s.air_flow_02_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.air_flow_02_mean - s.air_flow_02_avg) > 0.000000001 + 0.000000001 * ABS(s.air_flow_02_avg)
UNION ALL
SELECT a.hour, 'air_flow_03', a.air_flow_03_mean, s.air_flow_03_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.air_flow_03_mean - s.air_flow_03_avg) > 0.000000001 + 0.000000001 * ABS(s.air_flow_03_avg)
UNION ALL
SELECT a.hour, 'air_flow_04', a.air_flow_04_mean, s.air_flow_04_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.air_flow_04_mean - s.air_flow_04_avg) > 0.000000001 + 0.000000001 * ABS(s.air_flow_04_avg)
UNION ALL
SELECT a.hour, 'air_flow_05', a.air_flow_05_mean, s.air_flow_05_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.air_flow_05_mean - s.air_flow_05_avg) > 0.000000001 + 0.000000001 * ABS(s.air_flow_05_avg)
UNION ALL
SELECT a.hour, 'air_flow_06', a.air_flow_06_mean, s.air_flow_06_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.air_flow_06_mean - s.air_flow_06_avg) > 0.000000001 + 0.000000001 * ABS(s.air_flow_06_avg)
UNION ALL
SELECT a.hour, 'air_flow_07', a.air_flow_07_mean, s.air_flow_07_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.air_flow_07_mean - s.air_flow_07_avg) > 0.000000001 + 0.000000001 * ABS(s.air_flow_07_avg)
UNION ALL
SELECT a.hour, 'level_01', a.level_01_mean, s.level_01_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.level_01_mean - s.level_01_avg) > 0.000000001 + 0.000000001 * ABS(s.level_01_avg)
UNION ALL
SELECT a.hour, 'level_02', a.level_02_mean, s.level_02_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.level_02_mean - s.level_02_avg) > 0.000000001 + 0.000000001 * ABS(s.level_02_avg)
UNION ALL
SELECT a.hour, 'level_03', a.level_03_mean, s.level_03_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.level_03_mean - s.level_03_avg) > 0.000000001 + 0.000000001 * ABS(s.level_03_avg)
UNION ALL
SELECT a.hour, 'level_04', a.level_04_mean, s.level_04_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.level_04_mean - s.level_04_avg) > 0.000000001 + 0.000000001 * ABS(s.level_04_avg)
UNION ALL
SELECT a.hour, 'level_05', a.level_05_mean, s.level_05_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.level_05_mean - s.level_05_avg) > 0.000000001 + 0.000000001 * ABS(s.level_05_avg)
UNION ALL
SELECT a.hour, 'level_06', a.level_06_mean, s.level_06_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.level_06_mean - s.level_06_avg) > 0.000000001 + 0.000000001 * ABS(s.level_06_avg)
UNION ALL
SELECT a.hour, 'level_07', a.level_07_mean, s.level_07_avg FROM hour_aggregates AS a JOIN stats AS s ON s.hour = a.hour
WHERE ABS(a.level_07_mean - s.level_07_avg) > 0.000000001 + 0.000000001 * ABS(s.level_07_avg)
ORDER BY 1, 2;
