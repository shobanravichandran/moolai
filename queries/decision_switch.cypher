// "Why did they switch from X to Y?": decisions whose extracted MOVES_FROM matches $x and MOVES_TO matches $y.
// Either side may be empty ('' matches anything). Matching is substring both ways, lower-case.
MATCH (d:Decision)-[:MOVES_FROM]->(a:Technology)
MATCH (d)-[:MOVES_TO]->(b:Technology)
WHERE ($x = '' OR a.name CONTAINS $x OR $x CONTAINS a.name)
  AND ($y = '' OR b.name CONTAINS $y OR $y CONTAINS b.name)
RETURN d.id AS id, d.title AS title, d.status AS status, d.stage AS stage, d.url AS url, d.brief AS brief,
  d.rationale AS rationale, a.name AS moves_from, b.name AS moves_to, d.created AS created
ORDER BY created DESC
LIMIT $k
