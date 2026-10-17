// Before re-loading KEPs, drop their people/team/ref edges so edits to kep.yaml are reflected.
// Only outgoing refs are dropped: other KEPs' REPLACES / SEE_ALSO edges into these stay.
UNWIND $ids AS id
MATCH (d:Decision {id: id})
OPTIONAL MATCH (:Person)-[p:AUTHORED|REVIEWER_OF|APPROVER_OF]->(d)
DELETE p
WITH DISTINCT d
OPTIONAL MATCH (d)-[o:OWNED_BY|INVOLVES|REPLACES|SEE_ALSO]->()
DELETE o
