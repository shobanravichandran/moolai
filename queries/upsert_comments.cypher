// Human comments on PRs and issues (bodies trimmed). Bot comments are not stored.
UNWIND $rows AS r
MERGE (c:Comment {id: r.id})
SET c.body = r.body, c.created_at = r.created_at, c.url = r.url
WITH c, r
OPTIONAL MATCH (pr:PR {id: r.on})
OPTIONAL MATCH (i:Issue {id: r.on})
OPTIONAL MATCH (p:Person {login: r.author})
FOREACH (_ IN CASE WHEN pr IS NULL THEN [] ELSE [1] END | MERGE (c)-[:ON]->(pr))
FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END | MERGE (c)-[:ON]->(i))
FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (p)-[:AUTHORED]->(c))
