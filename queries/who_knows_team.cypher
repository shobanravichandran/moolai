// Experts for a team (SIG): same scoring as who_knows, over merged PRs tagged with the team, plus
// 2·ln(1 + KEPs the person authored or approved for that team).
MATCH (:Team {id: $team})<-[:TAGGED]-(q:PR)
WHERE q.merged_at < $as_of AND q.merged_at > $as_of - $window_s
MATCH (p:Person)-[r:AUTHORED|REVIEWED]->(q)
WHERE NOT coalesce(p.is_bot, false)
WITH p, q,
  max(CASE WHEN type(r) = 'AUTHORED' THEN 0.7 WHEN r.state IN ['APPROVED', 'LGTM'] THEN 1.0 ELSE 0.6 END) AS role,
  max(CASE WHEN type(r) = 'AUTHORED' THEN 1 ELSE 0 END) AS authored,
  max(CASE WHEN type(r) = 'REVIEWED' THEN 1 ELSE 0 END) AS reviewed
WITH p,
  sum(role * exp(-0.0077016 * ($as_of - q.merged_at) / 86400.0) / sqrt(toFloat(q.n_components))) AS activity,
  sum(authored) AS authored, sum(reviewed) AS reviewed, max(q.merged_at) AS last_active
OPTIONAL MATCH (p)-[:AUTHORED|APPROVER_OF]->(d:Decision)-[:OWNED_BY]->(:Team {id: $team})
WITH p, activity, authored, reviewed, last_active, collect(DISTINCT d.id) AS keps
RETURN p.login AS login, activity + 2.0 * log(1.0 + size(keps)) AS score, activity, authored, reviewed, keps,
  last_active
ORDER BY score DESC
LIMIT $k
