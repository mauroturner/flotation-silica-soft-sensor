-- The calendar (plan, section 19): every day from the first to the last that has an hour of the data or an hour that was estimated, one row per day, with the names in Spanish
-- (``ref_month`` and ``ref_weekday``) and the week of the test (weeks of 7 days from its first day; empty outside it). It reads the warehouse, not the other marts.
DROP TABLE IF EXISTS star_dim_date;

CREATE TABLE star_dim_date AS
WITH RECURSIVE bounds AS (
    SELECT MIN(date(h)) AS first_day, MAX(date(h)) AS last_day FROM (
        SELECT hour AS h FROM lab_hours WHERE hour < :as_of
        UNION ALL
        SELECT target_hour FROM estimates WHERE issue_at <= :as_of
    )
), calendar(day) AS (
    SELECT first_day FROM bounds WHERE first_day IS NOT NULL
    UNION ALL
    SELECT date(day, '+1 day') FROM calendar, bounds WHERE day < bounds.last_day
)
SELECT CAST(strftime('%Y%m%d', c.day) AS INTEGER) AS date_key, c.day AS date, CAST(strftime('%Y', c.day) AS INTEGER) AS year, CAST(strftime('%m', c.day) AS INTEGER) AS month,
       m.month_es AS month_name_es, w.weekday_es AS weekday_es,
       CASE WHEN c.day BETWEEN date(:test_first) AND date(:test_last)
            THEN CAST((julianday(c.day) - julianday(date(:test_first))) / 7 AS INTEGER) + 1 END AS test_week
FROM calendar AS c
JOIN ref_month AS m ON m.month = CAST(strftime('%m', c.day) AS INTEGER)
JOIN ref_weekday AS w ON w.weekday = CASE WHEN strftime('%w', c.day) = '0' THEN 7 ELSE CAST(strftime('%w', c.day) AS INTEGER) END
ORDER BY c.day;
