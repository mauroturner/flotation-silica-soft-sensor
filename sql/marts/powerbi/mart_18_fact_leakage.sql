-- The demonstration of the leak (plan, section 19): the random split and the iron of the concentrate against the blocks.
DROP TABLE IF EXISTS star_fact_leakage;

CREATE TABLE star_fact_leakage AS
SELECT l.check_id AS "check", l.description_es AS check_es, l.mae, l.r2, l.note_es
FROM eval_leakage AS l
JOIN ref_shown AS r ON r.table_name = 'eval_leakage' AND r.seal_state = l.seal_state
ORDER BY l.check_id;
