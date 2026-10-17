// KEP numbers owned by the given teams (scope for implementation-PR backfill).
MATCH (d:Decision {kind: 'kep'})-[:OWNED_BY]->(t:Team)
WHERE t.id IN $teams
RETURN d.number AS number
