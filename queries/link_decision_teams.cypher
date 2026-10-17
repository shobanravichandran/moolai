// Participating SIGs of a KEP.
UNWIND $rows AS r
MATCH (d:Decision {id: r.decision})
MERGE (t:Team {id: r.team})
MERGE (d)-[:INVOLVES]->(t)
