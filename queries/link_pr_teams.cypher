// (PR)-[:TAGGED]->(Team) from sig/* and wg/* labels.
UNWIND $rows AS r
MATCH (pr:PR {id: r.pr})
MERGE (t:Team {id: r.team})
ON CREATE SET t.name = r.name, t.kind = r.kind
MERGE (pr)-[:TAGGED]->(t)
