-- The block of each hour (D10; plan, section 9): rebuilt by sql/staging/stg_hours.sql from the split of the configuration that the caller gives,
-- so it is always the block of the split in force. split.block_of (U08) is the same rule in Python and a test compares them.

CREATE TABLE IF NOT EXISTS hour_blocks (
    hour TEXT PRIMARY KEY REFERENCES lab_hours (hour),
    block TEXT NOT NULL CHECK (block IN ('train', 'purge_1', 'valid_v1', 'purge_v', 'valid_v2', 'purge_2', 'test', 'outside'))
);
