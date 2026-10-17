// Node counts per label (health check and ingest sanity).
MATCH (n)
RETURN labels(n)[0] AS label, count(n) AS n
ORDER BY n DESC
