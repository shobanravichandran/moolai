// Ground truth for the backtest: humans other than the author who reviewed the PR.
MATCH (p:Person)-[:REVIEWED]->(t:PR {id: $pr_id})
WHERE NOT coalesce(p.is_bot, false) AND NOT (p)-[:AUTHORED]->(t)
RETURN p.login AS login
