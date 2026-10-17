// Experts on a component, ranked.
// activity = Σ over merged PRs touching the component in the window:
//            role (approve/lgtm 1.0, authored 0.7, other review 0.6) · 2^(-age/90 days) / √(components the PR spans)
// keps  = KEPs the person authored or approved, owned by the component's team and implemented by PRs touching it.
// score = activity + 2·ln(1 + |keps|)   (design work counts, but with diminishing returns)
MATCH (:Component {id: $component})<-[:PART_OF]-(:File)<-[:TOUCHES]-(q:PR)
WHERE q.merged_at < $as_of AND q.merged_at > $as_of - $window_s
WITH DISTINCT q
MATCH (p:Person)-[r:AUTHORED|REVIEWED]->(q)
WHERE NOT coalesce(p.is_bot, false)
WITH p, q,
  max(CASE WHEN type(r) = 'AUTHORED' THEN 0.7 WHEN r.state IN ['APPROVED', 'LGTM'] THEN 1.0 ELSE 0.6 END) AS role,
  max(CASE WHEN type(r) = 'AUTHORED' THEN 1 ELSE 0 END) AS authored,
  max(CASE WHEN type(r) = 'REVIEWED' THEN 1 ELSE 0 END) AS reviewed
WITH p,
  sum(role * exp(-0.0077016 * ($as_of - q.merged_at) / 86400.0) / sqrt(toFloat(q.n_components))) AS activity,
  sum(authored) AS authored, sum(reviewed) AS reviewed, max(q.merged_at) AS last_active
OPTIONAL MATCH (p)-[:AUTHORED|APPROVER_OF]->(d:Decision)<-[:IMPLEMENTS]-(:PR)-[:TOUCHES]->(:File)
  -[:PART_OF]->(c:Component {id: $component})
WHERE (d)-[:OWNED_BY]->(:Team)<-[:OWNED_BY]-(c)
WITH p, activity, authored, reviewed, last_active, collect(DISTINCT d.id) AS keps
RETURN p.login AS login, activity + 2.0 * log(1.0 + size(keps)) AS score, activity, authored, reviewed, keps,
  last_active
ORDER BY score DESC
LIMIT $k
