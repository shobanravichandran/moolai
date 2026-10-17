// Named components (config/components.yaml) for pickers, busiest first.
MATCH (c:Component {kind: 'named'})
OPTIONAL MATCH (c)-[:OWNED_BY]->(t:Team)
RETURN c.id AS id, c.name AS name, t.id AS team, size([(c)<-[:PART_OF]-(f:File) | f]) AS files
ORDER BY files DESC
