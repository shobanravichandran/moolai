// A component: its team, aliases, and size (files and PRs seen).
MATCH (c:Component {id: $component})
RETURN c {.id, .name, .kind, .aliases} AS component,
  [(c)-[:OWNED_BY]->(t:Team) | t.id] AS team,
  size([(c)<-[:PART_OF]-(f:File) | f]) AS files,
  size([(c)<-[:PART_OF]-(:File)<-[:TOUCHES]-(q:PR) | q.id]) AS touches
