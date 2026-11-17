-- Each sensor in each closed hour, as the hour aggregates hold it (plan, section 19; R01 and R11): 19 rows per hour. An hour that had not closed at :as_of is not here.
DROP TABLE IF EXISTS star_fact_hour_process;

CREATE TABLE star_fact_hour_process AS
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'starch_flow' AS sensor_key, starch_flow_mean AS mean, starch_flow_std AS std, starch_flow_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'amina_flow' AS sensor_key, amina_flow_mean AS mean, amina_flow_std AS std, amina_flow_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'ore_pulp_flow' AS sensor_key, ore_pulp_flow_mean AS mean, ore_pulp_flow_std AS std, ore_pulp_flow_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'ore_pulp_ph' AS sensor_key, ore_pulp_ph_mean AS mean, ore_pulp_ph_std AS std, ore_pulp_ph_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'ore_pulp_density' AS sensor_key, ore_pulp_density_mean AS mean, ore_pulp_density_std AS std, ore_pulp_density_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'air_flow_01' AS sensor_key, air_flow_01_mean AS mean, air_flow_01_std AS std, air_flow_01_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'air_flow_02' AS sensor_key, air_flow_02_mean AS mean, air_flow_02_std AS std, air_flow_02_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'air_flow_03' AS sensor_key, air_flow_03_mean AS mean, air_flow_03_std AS std, air_flow_03_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'air_flow_04' AS sensor_key, air_flow_04_mean AS mean, air_flow_04_std AS std, air_flow_04_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'air_flow_05' AS sensor_key, air_flow_05_mean AS mean, air_flow_05_std AS std, air_flow_05_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'air_flow_06' AS sensor_key, air_flow_06_mean AS mean, air_flow_06_std AS std, air_flow_06_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'air_flow_07' AS sensor_key, air_flow_07_mean AS mean, air_flow_07_std AS std, air_flow_07_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'level_01' AS sensor_key, level_01_mean AS mean, level_01_std AS std, level_01_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'level_02' AS sensor_key, level_02_mean AS mean, level_02_std AS std, level_02_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'level_03' AS sensor_key, level_03_mean AS mean, level_03_std AS std, level_03_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'level_04' AS sensor_key, level_04_mean AS mean, level_04_std AS std, level_04_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'level_05' AS sensor_key, level_05_mean AS mean, level_05_std AS std, level_05_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'level_06' AS sensor_key, level_06_mean AS mean, level_06_std AS std, level_06_last AS "last"
FROM hour_aggregates WHERE hour < :as_of
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key, 'level_07' AS sensor_key, level_07_mean AS mean, level_07_std AS std, level_07_last AS "last"
FROM hour_aggregates WHERE hour < :as_of;
