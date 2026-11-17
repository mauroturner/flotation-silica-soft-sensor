-- The eight methods of the estimates (plan, sections 5 and 19; R09 and R10), from ``ref_method``. B* is not a method of its own: it is one of the rules, flagged in the facts.
DROP TABLE IF EXISTS star_dim_method;

CREATE TABLE star_dim_method AS
SELECT method_key, method_es, kind_es FROM ref_method ORDER BY sort_order;
