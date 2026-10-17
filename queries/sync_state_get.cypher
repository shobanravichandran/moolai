// Watermark for one source (a git sha or an updatedAt timestamp).
MATCH (s:SyncState {source: $source})
RETURN s.cursor AS cursor, s.last_run_at AS last_run_at, s.stats AS stats
