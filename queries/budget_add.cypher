// Add one /api/ask call's Claude cost to today's spend.
MERGE (b:Budget {day: $day})
SET b.spent_usd = coalesce(b.spent_usd, 0.0) + $usd
