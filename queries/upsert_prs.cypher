// Pull requests (fetched = true; implementation-PR stubs from tracking issues have only id/number/url).
UNWIND $rows AS r
MERGE (pr:PR {id: r.id})
SET pr += r.props
WITH pr, r
OPTIONAL MATCH (p:Person {login: r.author})
FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (p)-[:AUTHORED]->(pr))
