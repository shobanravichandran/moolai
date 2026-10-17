// The files in a component that changed most often in the window (merged PRs).
MATCH (:Component {id: $component})<-[:PART_OF]-(f:File)<-[:TOUCHES]-(q:PR)
WHERE q.merged_at < $as_of AND q.merged_at > $as_of - $window_s
RETURN f.path AS path, count(DISTINCT q) AS prs, max(q.merged_at) AS last_changed
ORDER BY prs DESC
LIMIT $limit
