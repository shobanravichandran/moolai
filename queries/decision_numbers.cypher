// KEP numbers already in the graph (so incremental loads can link to KEPs they didn't reload).
MATCH (d:Decision {kind: 'kep'})
RETURN d.number AS number
