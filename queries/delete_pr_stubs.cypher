// Remove linked-PR stubs that GitHub says are not pull requests (the link pointed at an issue).
// Only stubs (fetched = false) are ever deleted.
UNWIND $ids AS id
MATCH (pr:PR {id: id, fetched: false})
DETACH DELETE pr
