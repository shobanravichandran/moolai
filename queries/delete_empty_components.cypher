// Fallback ('dir') components left with no files after pruning.
MATCH (c:Component {kind: 'dir'})
WHERE NOT (c)<-[:PART_OF]-()
DETACH DELETE c
