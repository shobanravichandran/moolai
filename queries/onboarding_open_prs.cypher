// Work in flight: open PRs touching a component, most recently updated first.
MATCH (:Component {id: $component})<-[:PART_OF]-(:File)<-[:TOUCHES]-(q:PR {state: 'open'})
WITH DISTINCT q
RETURN q.id AS id, q.title AS title, q.url AS url, q.updated_at AS updated_at,
  [(a:Person)-[:AUTHORED]->(q) | a.login] AS author
ORDER BY updated_at DESC
LIMIT $limit
