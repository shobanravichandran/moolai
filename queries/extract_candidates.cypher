// KEPs to run decision extraction on: owned by the given teams, with the README sections the model reads.
MATCH (d:Decision {kind: 'kep'})-[:OWNED_BY]->(t:Team)
WHERE t.id IN $teams
RETURN d.id AS id, d.title AS title, d.status AS status, d.stage AS stage,
  d.summary AS summary, d.motivation AS motivation, d.alternatives AS alternatives
ORDER BY d.number
