// Backtest set: merged PRs in scope (tagged with one of $teams), created after $since, with at least one
// human reviewer other than the author. Most recent first.
MATCH (t:PR {fetched: true, state: 'merged'})-[:TAGGED]->(tm:Team)
WHERE tm.id IN $teams AND t.created_at > $since
WITH DISTINCT t
MATCH (p:Person)-[:REVIEWED]->(t)
WHERE NOT coalesce(p.is_bot, false) AND NOT (p)-[:AUTHORED]->(t)
WITH t, count(p) AS reviewers
RETURN t.id AS id, t.created_at AS created_at, [(t)-[:TAGGED]->(x:Team) | x.id] AS teams
ORDER BY t.merged_at DESC
LIMIT $limit
