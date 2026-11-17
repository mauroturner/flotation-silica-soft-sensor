-- Every hour, one by one, from the first hour with data to the last hour that was estimated, also the ones with no data (the gap of March, the hours after the data that the
-- last estimates are about): a continuous axis of time (plan, section 19; R01 to R03). ``lab_state`` is the state of the analysis of the hour as it was known at :as_of: ``fresh``,
-- ``interpolated`` or ``held`` once it had arrived, ``pending`` while it had not, ``missing`` when the warehouse has no hour. The block is the rule of D10 over the split in the
-- named parameters, the same as ``stg_hours.sql`` (a control compares them).
DROP TABLE IF EXISTS star_dim_hour;

CREATE TABLE star_dim_hour AS
WITH RECURSIVE bounds AS (
    SELECT MIN(h) AS first_hour, MAX(h) AS last_hour FROM (
        SELECT hour AS h FROM lab_hours WHERE hour < :as_of
        UNION ALL
        SELECT target_hour FROM estimates WHERE issue_at <= :as_of
    )
), calendar(hour) AS (
    SELECT first_hour FROM bounds WHERE first_hour IS NOT NULL
    UNION ALL
    SELECT datetime(hour, '+1 hour') FROM calendar, bounds WHERE hour < bounds.last_hour
), x AS (
    SELECT c.hour,
           CASE
               WHEN c.hour < :train_first THEN 'outside'
               WHEN c.hour <= :train_last THEN 'train'
               WHEN c.hour < :v1_first THEN 'purge_1'
               WHEN c.hour <= :v1_last THEN 'valid_v1'
               WHEN c.hour < :v2_first THEN 'purge_v'
               WHEN c.hour <= :v2_last THEN 'valid_v2'
               WHEN c.hour < :test_first THEN 'purge_2'
               WHEN c.hour <= :test_last THEN 'test'
               ELSE 'outside'
           END AS block,
           CASE WHEN k.hour IS NULL THEN 'missing' WHEN k.available_at > :as_of THEN 'pending' ELSE k.lab_state END AS lab_state,
           COALESCE(k.is_partial, 0) AS is_partial, COALESCE(k.rows, 0) AS rows
    FROM calendar AS c
    LEFT JOIN lab_hours AS k ON k.hour = c.hour AND k.hour < :as_of
)
SELECT CAST(strftime('%Y%m%d%H', x.hour) AS INTEGER) AS hour_key, x.hour AS hour, date(x.hour) AS date, CAST(strftime('%H', x.hour) AS INTEGER) AS hour_of_day,
       x.block, b.block_es, x.lab_state, s.lab_state_es, x.is_partial, x.rows
FROM x
JOIN ref_block AS b ON b.block = x.block
JOIN ref_lab_state AS s ON s.lab_state = x.lab_state
ORDER BY x.hour;
