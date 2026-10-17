// The PRs behind one person's expertise in a component (most recent first), with their role on each.
MATCH (:Component {id: $component})<-[:PART_OF]-(:File)<-[:TOUCHES]-(q:PR)
WHERE q.merged_at < $as_of AND q.merged_at > $as_of - $window_s
WITH DISTINCT q
MATCH (p:Person {login: $login})-[r:AUTHORED|REVIEWED]->(q)
RETURN q.id AS id, q.title AS title, q.url AS url, q.merged_at AS merged_at,
  collect(CASE type(r) WHEN 'AUTHORED' THEN 'author' ELSE toLower(r.state) END) AS roles
ORDER BY merged_at DESC
LIMIT $limit
