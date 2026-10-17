// Baseline 2 pool: everyone who reviewed a PR in the same components before $as_of. Picking at random from
// this pool approximates Prow's blunderbuss (a random reviewer from the OWNERS of the touched directories).
MATCH (t:PR {id: $pr_id})-[:TOUCHES]->(:File)-[:PART_OF]->(c:Component)
WITH DISTINCT c
MATCH (c)<-[:PART_OF]-(:File)<-[:TOUCHES]-(q:PR)<-[:REVIEWED]-(p:Person)
WHERE q.merged_at < $as_of AND q.merged_at > $as_of - $window_s
  AND NOT coalesce(p.is_bot, false) AND NOT p.login IN $exclude
RETURN DISTINCT p.login AS login
