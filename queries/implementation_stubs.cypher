// Linked-but-not-fetched implementation PRs for KEPs owned by the given teams.
MATCH (pr:PR {fetched: false})-[:IMPLEMENTS]->(:Decision)-[:OWNED_BY]->(t:Team)
WHERE t.id IN $teams
RETURN DISTINCT pr.number AS number
