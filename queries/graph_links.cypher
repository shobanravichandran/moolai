// Graph view: edges among the given nodes, plus PR -> Component when a PR touches a file in that component
// (files themselves aren't drawn).
MATCH (a)-[r]->(b)
WHERE ID(a) IN $nids AND ID(b) IN $nids
RETURN ID(a) AS source, ID(b) AS target, type(r) AS type
UNION
MATCH (a:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(c:Component)
WHERE ID(a) IN $nids AND ID(c) IN $nids
RETURN DISTINCT ID(a) AS source, ID(c) AS target, 'TOUCHES' AS type
