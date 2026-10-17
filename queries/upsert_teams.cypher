// Teams (SIGs, working groups) from KEP owning/participating SIGs.
UNWIND $rows AS r
MERGE (t:Team {id: r.id})
SET t.name = r.name, t.kind = r.kind
