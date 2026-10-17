// Issues (KEP tracking issues fill the stubs created by the KEP loader).
UNWIND $rows AS r
MERGE (i:Issue {id: r.id})
SET i += r.props
WITH i, r
OPTIONAL MATCH (p:Person {login: r.author})
FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (p)-[:AUTHORED]->(i))
