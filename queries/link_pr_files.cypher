// (PR)-[:TOUCHES]->(File)-[:PART_OF]->(Component). Components not in components.yaml are created as 'dir'.
UNWIND $rows AS r
MATCH (pr:PR {id: r.pr})
MERGE (f:File {id: r.file})
ON CREATE SET f.repo = r.repo, f.path = r.path
SET f.dir = r.dir
MERGE (c:Component {id: r.component})
ON CREATE SET c.name = r.component_name, c.kind = 'dir'
MERGE (f)-[:PART_OF]->(c)
CREATE (pr)-[:TOUCHES {additions: r.additions, deletions: r.deletions}]->(f)
