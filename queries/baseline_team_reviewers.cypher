// Baseline 1: the busiest reviewers of PRs tagged with the same teams, before $as_of (no file knowledge).
MATCH (tm:Team)<-[:TAGGED]-(q:PR)<-[:REVIEWED]-(p:Person)
WHERE tm.id IN $teams AND q.merged_at < $as_of AND q.merged_at > $as_of - $window_s
  AND NOT coalesce(p.is_bot, false) AND NOT p.login IN $exclude
RETURN p.login AS login, count(DISTINCT q) AS reviews
ORDER BY reviews DESC
LIMIT $k
