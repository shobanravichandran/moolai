// (PR)-[:FIXES]->(Issue) from GitHub's closingIssuesReferences (cross-repo allowed).
UNWIND $rows AS r
MATCH (pr:PR {id: r.pr})
MERGE (i:Issue {id: r.issue})
ON CREATE SET i.repo = r.repo, i.number = r.number, i.kind = 'issue'
SET i.title = r.title, i.state = r.state, i.url = r.url
MERGE (pr)-[:FIXES]->(i)
