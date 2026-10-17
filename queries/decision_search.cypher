// Full-text search over decision titles and summaries. $q is a sanitized RediSearch query (terms OR-ed).
CALL db.idx.fulltext.queryNodes('Decision', $q) YIELD node, score
RETURN node.id AS id, node.title AS title, node.status AS status, node.stage AS stage,
  node.latest_milestone AS milestone, node.url AS url, score,
  [(node)-[:OWNED_BY]->(t:Team) | t.id] AS team
ORDER BY score DESC
LIMIT $k
