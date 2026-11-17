-- The tracking counts what it must (AC21): the estimates with numbers issued by :as_of whose analysis had arrived are exactly the rows of ``tracking`` ('tracked'), and those whose
-- analysis is also fresh are exactly the estimates of the star model that have an actual ('with_actual'). It recounts from ``estimates`` and ``lab_hours``, not from the tracking, so a
-- tracking left from another instant is found.
SELECT what, expected, shown FROM (
    SELECT 'tracked' AS what,
           (SELECT COUNT(*) FROM estimates AS e JOIN lab_hours AS l ON l.hour = e.target_hour
            WHERE e.status = 'ok' AND e.issue_at <= :as_of AND l.available_at <= :as_of) AS expected,
           (SELECT COUNT(*) FROM tracking) AS shown
    UNION ALL
    SELECT 'with_actual',
           (SELECT COUNT(*) FROM estimates AS e JOIN lab_hours AS l ON l.hour = e.target_hour
            WHERE e.status = 'ok' AND e.issue_at <= :as_of AND l.available_at <= :as_of AND l.lab_state = 'fresh'),
           (SELECT COUNT(*) FROM star_fact_estimate WHERE actual IS NOT NULL)
)
WHERE expected <> shown;
