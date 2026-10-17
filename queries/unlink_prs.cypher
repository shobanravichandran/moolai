// Before re-loading PRs, drop the edges a re-sync rebuilds: files, team tags, fixes and reviews.
// IMPLEMENTS edges are kept: they also come from tracking issues, and KEP references are rarely removed.
UNWIND $ids AS id
MATCH (pr:PR {id: id})
OPTIONAL MATCH (pr)-[o:TOUCHES|FIXES|TAGGED]->()
DELETE o
WITH DISTINCT pr
OPTIONAL MATCH (:Person)-[rv:REVIEWED]->(pr)
DELETE rv
