// A KEP's extracted decision (empty until moolai.extract has run for it).
MATCH (d:Decision {id: $id})
WHERE d.brief IS NOT NULL
RETURN d.brief AS brief, d.rationale AS rationale, d.alternatives_considered AS alternatives
