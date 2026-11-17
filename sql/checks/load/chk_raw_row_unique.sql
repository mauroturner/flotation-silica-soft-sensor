-- No two rows of an hour share their place in it (the key of a row is its row_id, and its position in the hour is unique too).
SELECT hour, row_in_hour, COUNT(*) AS copies FROM raw_rows GROUP BY hour, row_in_hour HAVING COUNT(*) > 1 ORDER BY hour, row_in_hour;
