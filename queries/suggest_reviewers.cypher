// Reviewer suggestions for a PR, using only PRs merged before $as_of (so the backtest can't see the future).
// Per component the PR touches:
//   for each earlier merged PR q in that component: match = 1.0 if q touched one of the same files,
//   0.5 if the same directory, 0.25 if only the same component;
//   person score s = Σ_q role (approve/lgtm 1.0, authored 0.7, other review 0.6) · match · 2^(-age/90 days)
//                    / √(components q spans)
// Each component's scores become shares (s / Σ s), weighted by the fraction of the PR's files in it, so a big,
// busy component can't drown out the one the PR is mostly about. The PR's author and bots are excluded.
// Backtest (docs/backtest.md): 53.6% hit@1, 76.1% hit@3 on 700 merged PRs vs 30.3% / 63.7% for SIG-only.
MATCH (t:PR {id: $pr_id})-[:TOUCHES]->(tf:File)-[:PART_OF]->(tc:Component)
WITH t, tc, collect(tf.id) AS cfiles, collect(DISTINCT tf.dir) AS cdirs
WITH t, collect({c: tc, n: size(cfiles), files: cfiles, dirs: cdirs}) AS comps, sum(size(cfiles)) AS total
OPTIONAL MATCH (ta:Person)-[:AUTHORED]->(t)
UNWIND comps AS cc
WITH t, ta, cc.c AS c, toFloat(cc.n) / total AS w, cc.files AS files, cc.dirs AS dirs
MATCH (c)<-[:PART_OF]-(f:File)<-[:TOUCHES]-(q:PR)
WHERE q <> t AND q.merged_at < $as_of AND q.merged_at > $as_of - $window_s
WITH ta, c, w, q, max(CASE WHEN f.id IN files THEN 1.0 WHEN f.dir IN dirs THEN 0.5 ELSE 0.25 END) AS match
MATCH (p:Person)-[r:AUTHORED|REVIEWED]->(q)
WHERE NOT coalesce(p.is_bot, false) AND (ta IS NULL OR p <> ta)
WITH p, c, w, q, match,
  max(CASE WHEN type(r) = 'AUTHORED' THEN 0.7 WHEN r.state IN ['APPROVED', 'LGTM'] THEN 1.0 ELSE 0.6 END) AS role
WITH p, c, w,
  sum(role * match * exp(-0.0077016 * ($as_of - q.merged_at) / 86400.0) / sqrt(toFloat(q.n_components))) AS s,
  collect(q.id) AS prs, collect(CASE WHEN match = 1.0 THEN q.id END) AS same_file_prs, max(q.merged_at) AS last
WITH c, w, collect({login: p.login, s: s, prs: prs, same: same_file_prs, last: last}) AS people, sum(s) AS total_c
UNWIND people AS x
WITH x.login AS login, sum(w * x.s / total_c) AS score, collect(c.id) AS components,
  collect(x.prs) AS prs, collect(x.same) AS same_file_prs, max(x.last) AS last_active
RETURN login, score, components, prs, same_file_prs, last_active
ORDER BY score DESC
LIMIT $k
