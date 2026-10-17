// PR numbers already fetched in full for a repo.
MATCH (pr:PR {repo: $repo, fetched: true})
RETURN pr.number AS number
