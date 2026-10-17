// One decision and everything it connects to, as lists (no cartesian blow-up).
// Each pattern comprehension uses its own variable names: FalkorDB 4.22 returns [] for a later comprehension
// that reuses a name from an earlier one.
MATCH (d:Decision {id: $id})
RETURN d {.id, .kind, .title, .status, .stage, .latest_milestone, .created, .summary, .url} AS decision,
  [(d)-[:OWNED_BY]->(own:Team) | own.id] AS team,
  [(d)-[:INVOLVES]->(inv:Team) | inv.id] AS involves,
  [(d)-[:DISCUSSED_IN]->(disc) | disc {.id, .title, .url}] AS discussed_in,
  [(impl:PR)-[:IMPLEMENTS]->(d) | impl {.id, .title, .url, .merged_at}] AS implemented_by,
  [(au:Person)-[:AUTHORED]->(d) | au.login] AS authors,
  [(rv:Person)-[:REVIEWER_OF]->(d) | rv.login] AS reviewers,
  [(ap:Person)-[apr:APPROVER_OF]->(d) | {login: ap.login, kind: apr.kind}] AS approvers,
  [(d)-[:REPLACES]->(old:Decision) | old {.id, .title, .status, .url}] AS replaces,
  [(newer:Decision)-[:REPLACES]->(d) | newer {.id, .title, .status, .url}] AS replaced_by,
  [(d)-[:SEE_ALSO]->(rel:Decision) | rel {.id, .title, .url}] AS see_also,
  [(d)-[:MOVES_FROM]->(src:Technology) | src.name] AS moves_from,
  [(d)-[:MOVES_TO]->(dst:Technology) | dst.name] AS moves_to
