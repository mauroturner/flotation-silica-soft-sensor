-- The quality of the data day by day (plan, section 19; R04), from the first to the last day that has hours (the gap of March included, as days with no hours): the hours
-- with data, the hours missing from the grid inside that period, the partial hours, the analyses that had arrived at :as_of by state and the hours where a sensor did not
-- move (its standard deviation is exactly 0, as rule I03 says) or the feed had not changed for 24 hours or more (rule I02). An analysis that has not arrived is not
-- counted in a state or in the feed: its state is not known yet.
DROP TABLE IF EXISTS star_fact_data_quality;

CREATE TABLE star_fact_data_quality AS
WITH span AS (
    SELECT MIN(hour) AS first_hour, MAX(hour) AS last_hour FROM lab_hours WHERE hour < :as_of
), per_day AS (
    SELECT date(l.hour) AS day, COUNT(*) AS hours, SUM(l.is_partial) AS partial_hours,
           SUM(CASE WHEN l.available_at <= :as_of AND l.lab_state = 'fresh' THEN 1 ELSE 0 END) AS fresh,
           SUM(CASE WHEN l.available_at <= :as_of AND l.lab_state = 'interpolated' THEN 1 ELSE 0 END) AS interpolated,
           SUM(CASE WHEN l.available_at <= :as_of AND l.lab_state = 'held' THEN 1 ELSE 0 END) AS held,
           SUM(CASE WHEN a.starch_flow_std = 0 OR a.amina_flow_std = 0 OR a.ore_pulp_flow_std = 0 OR a.ore_pulp_ph_std = 0 OR a.ore_pulp_density_std = 0 OR a.air_flow_01_std = 0 OR a.air_flow_02_std = 0 OR a.air_flow_03_std = 0 OR a.air_flow_04_std = 0 OR a.air_flow_05_std = 0 OR a.air_flow_06_std = 0 OR a.air_flow_07_std = 0 OR a.level_01_std = 0 OR a.level_02_std = 0 OR a.level_03_std = 0 OR a.level_04_std = 0 OR a.level_05_std = 0 OR a.level_06_std = 0 OR a.level_07_std = 0 THEN 1 ELSE 0 END) AS stuck_sensor_hours,
           SUM(CASE WHEN l.available_at <= :as_of AND (l.feed_silica_age_h >= 24 OR l.feed_iron_age_h >= 24) THEN 1 ELSE 0 END) AS feed_unchanged_24h
    FROM lab_hours AS l JOIN hour_aggregates AS a ON a.hour = l.hour
    WHERE l.hour < :as_of
    GROUP BY date(l.hour)
), gaps AS (
    SELECT h.date AS day, COUNT(*) AS missing_hours
    FROM star_dim_hour AS h, span
    WHERE h.lab_state = 'missing' AND h.hour > span.first_hour AND h.hour < span.last_hour
    GROUP BY h.date
)
SELECT d.date_key, COALESCE(p.hours, 0) AS hours, COALESCE(g.missing_hours, 0) AS missing_hours, COALESCE(p.partial_hours, 0) AS partial_hours,
       COALESCE(p.fresh, 0) AS fresh, COALESCE(p.interpolated, 0) AS interpolated, COALESCE(p.held, 0) AS held,
       COALESCE(p.stuck_sensor_hours, 0) AS stuck_sensor_hours, COALESCE(p.feed_unchanged_24h, 0) AS feed_unchanged_24h
FROM star_dim_date AS d, span
LEFT JOIN per_day AS p ON p.day = d.date
LEFT JOIN gaps AS g ON g.day = d.date
WHERE d.date BETWEEN date(span.first_hour) AND date(span.last_hour)
ORDER BY d.date_key;
