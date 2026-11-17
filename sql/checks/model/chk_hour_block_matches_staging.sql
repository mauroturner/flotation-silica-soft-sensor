-- The block of an hour in the star model is the one of ``hour_blocks`` (the rule of D10 in SQL is written twice: here and in ``stg_hours.sql``). A violation is the hour and both blocks.
SELECT h.hour, h.block AS star_block, b.block AS staging_block
FROM star_dim_hour AS h
JOIN hour_blocks AS b ON b.hour = h.hour
WHERE h.block <> b.block;
