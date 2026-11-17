-- The hours known at the instant :as_of (plan, section 7): those that had closed (the hour h covers [h, h + 1 h), so h < :as_of), each with its
-- analysis, its arrival, its aggregates and its block. The block is the rule of D10 over the split that comes in the named parameters: before
-- train_first or after test_last an hour is outside; between two blocks it is a purge. The text format of an hour sorts as time does.

DELETE FROM hour_blocks;

INSERT INTO hour_blocks (hour, block)
SELECT hour,
    CASE
        WHEN hour < :train_first THEN 'outside'
        WHEN hour <= :train_last THEN 'train'
        WHEN hour < :v1_first THEN 'purge_1'
        WHEN hour <= :v1_last THEN 'valid_v1'
        WHEN hour < :v2_first THEN 'purge_v'
        WHEN hour <= :v2_last THEN 'valid_v2'
        WHEN hour < :test_first THEN 'purge_2'
        WHEN hour <= :test_last THEN 'test'
        ELSE 'outside'
    END
FROM lab_hours;

DROP TABLE IF EXISTS stg_hours;

CREATE TABLE stg_hours AS
SELECT
    l.hour, l.delivery_id, l.rows, l.is_partial, l.silica_pct, l.iron_conc_pct, l.feed_silica_pct, l.feed_iron_pct, l.lab_state,
    l.feed_silica_age_h, l.feed_iron_age_h, l.available_at, b.block,
    a.starch_flow_mean,
    a.starch_flow_std,
    a.starch_flow_last,
    a.amina_flow_mean,
    a.amina_flow_std,
    a.amina_flow_last,
    a.ore_pulp_flow_mean,
    a.ore_pulp_flow_std,
    a.ore_pulp_flow_last,
    a.ore_pulp_ph_mean,
    a.ore_pulp_ph_std,
    a.ore_pulp_ph_last,
    a.ore_pulp_density_mean,
    a.ore_pulp_density_std,
    a.ore_pulp_density_last,
    a.air_flow_01_mean,
    a.air_flow_01_std,
    a.air_flow_01_last,
    a.air_flow_02_mean,
    a.air_flow_02_std,
    a.air_flow_02_last,
    a.air_flow_03_mean,
    a.air_flow_03_std,
    a.air_flow_03_last,
    a.air_flow_04_mean,
    a.air_flow_04_std,
    a.air_flow_04_last,
    a.air_flow_05_mean,
    a.air_flow_05_std,
    a.air_flow_05_last,
    a.air_flow_06_mean,
    a.air_flow_06_std,
    a.air_flow_06_last,
    a.air_flow_07_mean,
    a.air_flow_07_std,
    a.air_flow_07_last,
    a.level_01_mean,
    a.level_01_std,
    a.level_01_last,
    a.level_02_mean,
    a.level_02_std,
    a.level_02_last,
    a.level_03_mean,
    a.level_03_std,
    a.level_03_last,
    a.level_04_mean,
    a.level_04_std,
    a.level_04_last,
    a.level_05_mean,
    a.level_05_std,
    a.level_05_last,
    a.level_06_mean,
    a.level_06_std,
    a.level_06_last,
    a.level_07_mean,
    a.level_07_std,
    a.level_07_last
FROM lab_hours AS l
JOIN hour_aggregates AS a ON a.hour = l.hour
JOIN hour_blocks AS b ON b.hour = l.hour
WHERE l.hour < :as_of
ORDER BY l.hour;
