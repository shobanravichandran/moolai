// Claude spend so far today (shared daily cap for the hosted demo).
MATCH (b:Budget {day: $day})
RETURN b.spent_usd AS spent
