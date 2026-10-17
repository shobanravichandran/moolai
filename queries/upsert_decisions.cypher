// KEP -> Decision, owned by its SIG, discussed in its tracking issue (issue number = KEP number).
// The tracking Issue starts as a stub; the GitHub ingester fills in its title, state and comments.
UNWIND $rows AS r
MERGE (d:Decision {id: r.id})
SET d += r.props
MERGE (t:Team {id: r.team})
MERGE (d)-[:OWNED_BY]->(t)
MERGE (i:Issue {id: r.issue_id})
ON CREATE SET i.repo = r.issue_repo, i.number = r.number, i.kind = 'kep-tracking', i.url = r.issue_url
MERGE (d)-[:DISCUSSED_IN]->(i)
