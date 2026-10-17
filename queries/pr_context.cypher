// A PR at a glance: who opened it, which components and teams it touches, who reviewed it so far.
MATCH (t:PR {id: $pr_id})
RETURN t {.id, .title, .url, .state, .created_at, .merged_at, .n_components, .files_total} AS pr,
  [(au:Person)-[:AUTHORED]->(t) | au.login] AS author,
  [(t)-[:TOUCHES]->(:File)-[:PART_OF]->(c:Component) | c.id] AS components,
  [(t)-[:TAGGED]->(tm:Team) | tm.id] AS teams,
  [(rv:Person)-[r:REVIEWED]->(t) WHERE NOT coalesce(rv.is_bot, false) | {login: rv.login, state: r.state}] AS reviewers,
  [(t)-[:IMPLEMENTS]->(d:Decision) | d.id] AS decisions
