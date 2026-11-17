-- The horizons of the model (plan, section 19; R05 to R08), from ``ref_horizon``.
DROP TABLE IF EXISTS star_dim_horizon;

CREATE TABLE star_dim_horizon AS
SELECT horizon_key, horizon_es, hours_ahead FROM ref_horizon ORDER BY horizon_key;
