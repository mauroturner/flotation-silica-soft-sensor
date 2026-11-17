-- Every analysis arrives latency_hours after its hour (D06): computed here from the hour and the latency of the configuration, not read back.
SELECT hour, available_at, datetime(hour, '+' || :latency_hours || ' hours') AS expected
FROM lab_hours WHERE available_at <> datetime(hour, '+' || :latency_hours || ' hours') ORDER BY hour;
