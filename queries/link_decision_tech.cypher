// Write a KEP's extracted decision: brief, rationale, alternatives considered, and what it moves from / to.
// Earlier MOVES_FROM / MOVES_TO edges of the KEP are replaced. Technology nodes are shared across KEPs.
UNWIND $rows AS r
MATCH (d:Decision {id: r.decision})
SET d.brief = r.summary, d.rationale = r.rationale, d.alternatives_considered = r.alternatives
WITH d, r
OPTIONAL MATCH (d)-[old:MOVES_FROM|MOVES_TO]->(:Technology)
DELETE old
WITH DISTINCT d, r
FOREACH (name IN r.from | MERGE (t:Technology {name: name}) MERGE (d)-[:MOVES_FROM]->(t))
FOREACH (name IN r.to | MERGE (t:Technology {name: name}) MERGE (d)-[:MOVES_TO]->(t))
