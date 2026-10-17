// Named components from config/components.yaml, each owned by a team.
UNWIND $rows AS r
MERGE (c:Component {id: r.id})
SET c.name = r.name, c.kind = 'named', c.aliases = r.aliases
WITH c, r
WHERE r.team IS NOT NULL
MERGE (t:Team {id: r.team})
MERGE (c)-[:OWNED_BY]->(t)
