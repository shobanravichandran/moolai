// KEP -> KEP links from kep.yaml: replaces / superseded-by (as REPLACES) and see-also.
UNWIND $rows AS r
MATCH (a:Decision {id: r.from}), (b:Decision {id: r.to})
FOREACH (_ IN CASE WHEN r.rel = 'replaces' THEN [1] ELSE [] END | MERGE (a)-[:REPLACES]->(b))
FOREACH (_ IN CASE WHEN r.rel = 'see_also' THEN [1] ELSE [] END | MERGE (a)-[:SEE_ALSO]->(b))
