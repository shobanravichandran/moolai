// Teams nothing points at any more (e.g. a SIG alias that was later normalized).
MATCH (t:Team)
WHERE NOT (t)--()
DELETE t
