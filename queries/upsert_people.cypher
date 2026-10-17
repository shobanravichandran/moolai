// GitHub users seen on PRs, reviews and comments. Logins are lower-cased; bots are flagged, never dropped.
UNWIND $rows AS r
MERGE (p:Person {login: r.login})
ON CREATE SET p.url = 'https://github.com/' + r.login
SET p.is_bot = coalesce(p.is_bot, false) OR r.is_bot
