-- The analysis of each closed hour, shown only from its arrival (plan, section 19; R02; D06): while ``available_at`` is later than :as_of the hour is ``pending`` and no value of the
-- laboratory is in the row, not even the feed's, which comes from the same analysis. An hour that had not closed at :as_of is not here.
DROP TABLE IF EXISTS star_fact_hour_lab;

CREATE TABLE star_fact_hour_lab AS
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER) AS hour_key,
       CASE WHEN available_at <= :as_of THEN silica_pct END AS silica_pct,
       CASE WHEN available_at <= :as_of THEN iron_conc_pct END AS iron_conc_pct,
       CASE WHEN available_at <= :as_of THEN feed_silica_pct END AS feed_silica_pct,
       CASE WHEN available_at <= :as_of THEN feed_iron_pct END AS feed_iron_pct,
       CASE WHEN available_at <= :as_of THEN lab_state ELSE 'pending' END AS lab_state,
       CASE WHEN available_at <= :as_of THEN feed_silica_age_h END AS feed_silica_age_h,
       CASE WHEN available_at <= :as_of THEN feed_iron_age_h END AS feed_iron_age_h,
       available_at
FROM lab_hours
WHERE hour < :as_of
ORDER BY hour;
