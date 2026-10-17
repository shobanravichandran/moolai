// KEP authors, reviewers and approvers (kind 'sig' from kep.yaml, 'prr' from prod-readiness/).
UNWIND $rows AS r
MATCH (d:Decision {id: r.decision})
MERGE (p:Person {login: r.login})
ON CREATE SET p.is_bot = false, p.url = 'https://github.com/' + r.login
FOREACH (_ IN CASE WHEN r.role = 'author' THEN [1] ELSE [] END | MERGE (p)-[:AUTHORED]->(d))
FOREACH (_ IN CASE WHEN r.role = 'reviewer' THEN [1] ELSE [] END | MERGE (p)-[:REVIEWER_OF]->(d))
FOREACH (_ IN CASE WHEN r.role = 'approver' THEN [1] ELSE [] END | MERGE (p)-[:APPROVER_OF {kind: r.kind}]->(d))
