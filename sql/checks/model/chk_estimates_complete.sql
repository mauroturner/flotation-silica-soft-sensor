-- Every estimate issued by :as_of is in the star model once, with the status it had (AC21): the numbers of rows by status of ``estimates`` against those of ``star_fact_estimate``.
SELECT e.status, e.issued, COALESCE(s.shown, 0) AS shown
FROM (SELECT status, COUNT(*) AS issued FROM estimates WHERE issue_at <= :as_of GROUP BY status) AS e
LEFT JOIN (SELECT status, COUNT(*) AS shown FROM star_fact_estimate GROUP BY status) AS s ON s.status = e.status
WHERE e.issued <> COALESCE(s.shown, 0)
UNION ALL
SELECT s.status, 0, s.shown
FROM (SELECT status, COUNT(*) AS shown FROM star_fact_estimate GROUP BY status) AS s
WHERE s.status NOT IN (SELECT status FROM estimates WHERE issue_at <= :as_of);
