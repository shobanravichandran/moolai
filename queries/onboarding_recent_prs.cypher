// Recently merged PRs in a component, with authors.
MATCH (:Component {id: $component})<-[:PART_OF]-(:File)<-[:TOUCHES]-(q:PR)
WHERE q.merged_at < $as_of
WITH DISTINCT q
RETURN q.id AS id, q.title AS title, q.url AS url, q.merged_at AS merged_at,
  [(a:Person)-[:AUTHORED]->(q) | a.login] AS author
ORDER BY merged_at DESC
LIMIT $limit
