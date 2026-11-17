-- The frozen model of the launch, one row per horizon (plan, section 19; R14), from ``ref_model``, which reads the registry and the seal.
DROP TABLE IF EXISTS star_dim_model;

CREATE TABLE star_dim_model AS
SELECT model_key, model_version, horizon_key, family, feature_set, target_es, min_samples_leaf, half_width, b_star, b2_k, trained_on_es, config_sha256, seal_state
FROM ref_model ORDER BY horizon_key;
