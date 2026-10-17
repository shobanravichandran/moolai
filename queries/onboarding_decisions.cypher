// KEPs that shaped a component: decisions implemented by PRs that touched it (any age), most-implemented first.
MATCH (:Component {id: $component})<-[:PART_OF]-(:File)<-[:TOUCHES]-(q:PR)-[:IMPLEMENTS]->(d:Decision)
WITH d, count(DISTINCT q) AS prs, max(q.merged_at) AS last_pr
RETURN d.id AS id, d.title AS title, d.status AS status, d.stage AS stage, d.latest_milestone AS milestone,
  d.url AS url, prs, last_pr
ORDER BY prs DESC, last_pr DESC
LIMIT $limit
