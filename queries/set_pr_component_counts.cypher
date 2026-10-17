// Repair: PR.n_components = distinct components a fetched PR touches (at least 1).
MATCH (pr:PR {fetched: true})
OPTIONAL MATCH (pr)-[:TOUCHES]->(:File)-[:PART_OF]->(c:Component)
WITH pr, count(DISTINCT c) AS n
SET pr.n_components = CASE WHEN n < 1 THEN 1 ELSE n END
RETURN count(pr) AS updated
