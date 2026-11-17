-- The rule that is B* of a horizon is flagged in at most one row by block and horizon (plan, section 19): two flags would make a card that reads «el MAE de B*» ambiguous.
SELECT scope, horizon_key, seal_state, SUM(is_b_star) AS flagged
FROM star_fact_method_metrics
GROUP BY scope, horizon_key, seal_state
HAVING SUM(is_b_star) > 1;
