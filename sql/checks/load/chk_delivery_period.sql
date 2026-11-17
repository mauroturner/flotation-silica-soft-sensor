-- Every row and every hour was loaded with the delivery whose period holds its hour (V11's second line); the close holds none.
SELECT 'lab_hours' AS table_name, l.hour, l.delivery_id
FROM lab_hours AS l JOIN deliveries AS d ON d.delivery_id = l.delivery_id
WHERE d.first_hour IS NULL OR l.hour < d.first_hour OR l.hour > d.last_hour
UNION ALL
SELECT 'raw_rows', r.hour, r.delivery_id
FROM raw_rows AS r JOIN deliveries AS d ON d.delivery_id = r.delivery_id
WHERE d.first_hour IS NULL OR r.hour < d.first_hour OR r.hour > d.last_hour
ORDER BY 1, 2, 3;
