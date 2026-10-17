// Advance a source's watermark after a successful load. last_run_at is epoch seconds.
MERGE (s:SyncState {source: $source})
SET s.cursor = $cursor, s.stats = $stats, s.last_run_at = timestamp() / 1000
