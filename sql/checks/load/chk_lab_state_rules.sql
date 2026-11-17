-- The state of each analysis against the hour before it (D05; plan, section 7). The ramp flag is not stored, so what is checked is what the
-- stored values say: a held hour repeats the hour an hour before it, an interpolated hour has that hour and differs from it (a ramp hour
-- changes within the hour, so the next hour's value is not its own), and a fresh hour never equals it (it would be held). After a gap there is
-- no hour before: the hour is none of the first two.
WITH h AS (
    SELECT l.hour, l.lab_state, l.silica_pct, p.silica_pct AS previous_silica
    FROM lab_hours AS l LEFT JOIN lab_hours AS p ON p.hour = datetime(l.hour, '-1 hour')
)
SELECT hour, lab_state, 'held_does_not_repeat_the_previous_hour' AS reason FROM h
WHERE lab_state = 'held' AND (previous_silica IS NULL OR previous_silica <> silica_pct)
UNION ALL
SELECT hour, lab_state, 'interpolated_without_a_different_previous_hour' FROM h
WHERE lab_state = 'interpolated' AND (previous_silica IS NULL OR previous_silica = silica_pct)
UNION ALL
SELECT hour, lab_state, 'fresh_equals_the_previous_hour' FROM h
WHERE lab_state = 'fresh' AND previous_silica = silica_pct
ORDER BY 1, 3;
