// One-off / repair: File.dir and PR.n_components for nodes loaded before these properties existed.
// New ingests set both directly (link_pr_files, mapping.add_pr).
UNWIND $files AS r
MATCH (f:File {id: r.id})
SET f.dir = r.dir
