// One REVIEWED edge per (person, PR): strongest of GitHub review states and Prow /lgtm, /approve.
// via = 'github' | 'prow' | 'both'.
UNWIND $rows AS r
MATCH (pr:PR {id: r.pr}), (p:Person {login: r.login})
CREATE (p)-[:REVIEWED {state: r.state, at: r.at, via: r.via}]->(pr)
