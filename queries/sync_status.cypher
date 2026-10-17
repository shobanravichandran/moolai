// Last sync per source (watermark, time, counts).
MATCH (s:SyncState)
RETURN s.source AS source, s.cursor AS cursor, s.last_run_at AS last_run_at, s.stats AS stats
ORDER BY source
