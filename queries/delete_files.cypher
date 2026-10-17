// Remove File nodes (and their TOUCHES / PART_OF edges) that the skip rules in components.yaml now exclude.
UNWIND $ids AS id
MATCH (f:File {id: id})
DETACH DELETE f
