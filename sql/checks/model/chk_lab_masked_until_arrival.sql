-- No value of the laboratory is shown before its analysis arrives (D06): a row of ``star_fact_hour_lab`` with an analysis that arrives after :as_of must be ``pending`` and have no value
-- ('shown_early'), and one that had arrived must not be ('pending_late'). An hour of the star with no row of the warehouse, or the other way round, is 'not_in_the_warehouse'.
SELECT hour_key, 'shown_early' AS problem FROM star_fact_hour_lab
WHERE available_at > :as_of AND (lab_state <> 'pending' OR silica_pct IS NOT NULL OR iron_conc_pct IS NOT NULL OR feed_silica_pct IS NOT NULL OR feed_iron_pct IS NOT NULL
                                  OR feed_silica_age_h IS NOT NULL OR feed_iron_age_h IS NOT NULL)
UNION ALL
SELECT hour_key, 'pending_late' FROM star_fact_hour_lab WHERE available_at <= :as_of AND (lab_state = 'pending' OR silica_pct IS NULL)
UNION ALL
SELECT CAST(strftime('%Y%m%d%H', hour) AS INTEGER), 'not_in_the_warehouse' FROM lab_hours
WHERE hour < :as_of AND CAST(strftime('%Y%m%d%H', hour) AS INTEGER) NOT IN (SELECT hour_key FROM star_fact_hour_lab);
