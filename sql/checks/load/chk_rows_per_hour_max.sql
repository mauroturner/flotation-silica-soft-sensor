-- No hour has more rows than a complete one (V07's second line).
SELECT hour, COUNT(*) AS rows_in_hour FROM raw_rows GROUP BY hour HAVING COUNT(*) > :rows_per_hour ORDER BY hour;
