-- The result of each rule in each run (plan, section 19; R15): the severity and the status in Spanish, as the validation says them (``SEVERITY_ES`` and ``STATUS_ES``).
DROP TABLE IF EXISTS star_fact_validation;

CREATE TABLE star_fact_validation AS
SELECT run_key, rule_id, name_es,
       CASE severity WHEN 'blocking' THEN 'bloqueante' WHEN 'warning' THEN 'advertencia' ELSE 'informativa' END AS severity, scope, aggregation,
       CASE WHEN passed = 1 THEN 'pasa' WHEN severity = 'blocking' THEN 'falla' ELSE 'advierte' END AS status, rows_affected, hours_affected
FROM validation_results
ORDER BY run_key, rule_id;
