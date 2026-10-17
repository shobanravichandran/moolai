// Graph view: the nodes behind an answer's evidence. $keys are decision / PR / issue / component / team ids
// and people's logins.
MATCH (n)
WHERE n.id IN $keys OR n.login IN $keys
RETURN ID(n) AS nid, labels(n)[0] AS label, coalesce(n.id, n.login) AS key,
  coalesce(n.title, n.name, n.login, n.id) AS name, n.url AS url
