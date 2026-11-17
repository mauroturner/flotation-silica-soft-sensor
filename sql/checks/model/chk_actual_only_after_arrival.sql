-- An analysis is in an estimate only from its arrival, and it is the one that was stored (AC21, D06). A violation is an estimate of the star model that has an actual, an error or a
-- coverage although the analysis of its hour arrives after :as_of ('arrived_late'), or an actual that is not the fresh analysis of its hour ('not_the_analysis').
SELECT e.hour_key, e.horizon_key, 'arrived_late' AS problem, l.available_at AS detail
FROM star_fact_estimate AS e
JOIN lab_hours AS l ON CAST(strftime('%Y%m%d%H', l.hour) AS INTEGER) = e.hour_key
WHERE (e.actual IS NOT NULL OR e.abs_error IS NOT NULL OR e.abs_error_persistence IS NOT NULL OR e.abs_error_b_star IS NOT NULL OR e.covered IS NOT NULL)
  AND l.available_at > :as_of
UNION ALL
SELECT e.hour_key, e.horizon_key, 'not_the_analysis', l.lab_state
FROM star_fact_estimate AS e
JOIN lab_hours AS l ON CAST(strftime('%Y%m%d%H', l.hour) AS INTEGER) = e.hour_key
WHERE e.actual IS NOT NULL AND (l.lab_state <> 'fresh' OR ABS(e.actual - l.silica_pct) > 0.000000001);
