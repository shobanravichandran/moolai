// (PR)-[:IMPLEMENTS]->(Decision). The PR may be a stub (linked from a tracking issue, not fetched yet).
// via: 'pr_body' (KEP referenced in the PR) or 'tracking_issue' (PR linked from the KEP's tracking issue).
UNWIND $rows AS r
MATCH (d:Decision {id: r.decision})
MERGE (pr:PR {id: r.pr})
ON CREATE SET pr.repo = r.repo, pr.number = r.number, pr.url = r.url, pr.fetched = false
MERGE (pr)-[e:IMPLEMENTS]->(d)
ON CREATE SET e.via = r.via
