// Indexes for a company graph. Statements are separated by semicolons; re-running is safe.
// Range indexes on every node key (all ingestion is MERGE on these).
CREATE INDEX FOR (p:Person) ON (p.login);
CREATE INDEX FOR (t:Team) ON (t.id);
CREATE INDEX FOR (c:Component) ON (c.id);
CREATE INDEX FOR (f:File) ON (f.id);
CREATE INDEX FOR (pr:PR) ON (pr.id);
CREATE INDEX FOR (pr:PR) ON (pr.merged_at);
CREATE INDEX FOR (i:Issue) ON (i.id);
CREATE INDEX FOR (d:Decision) ON (d.id);
CREATE INDEX FOR (t:Technology) ON (t.name);
CREATE INDEX FOR (c:Commit) ON (c.sha);
CREATE INDEX FOR (c:Comment) ON (c.id);
CREATE INDEX FOR (r:Repo) ON (r.id);
CREATE INDEX FOR (s:SyncState) ON (s.source);
// Full-text indexes for entity resolution ("auth module", "nftables", "KEP about dockershim").
CALL db.idx.fulltext.createNodeIndex('Decision', 'title', 'summary');
CALL db.idx.fulltext.createNodeIndex('PR', 'title');
CALL db.idx.fulltext.createNodeIndex('Issue', 'title');
CALL db.idx.fulltext.createNodeIndex('Technology', 'name');
CALL db.idx.fulltext.createNodeIndex('Component', 'name');
CALL db.idx.fulltext.createNodeIndex('Person', 'login', 'name')
