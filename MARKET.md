# Market monitor

Authenticated page: /market. Start/stop polling every 60 seconds while visible; news refreshes every 5 minutes. No background worker, trading orders, account-position access, or AI calls in this screen.

Reference symbols: ^GSPC, ^FCHI, AMZN, GC=F, CL=F, KC=F. These are cash indices, a share, and futures, not Plus500 CFD prices. Public Yahoo Finance data can be delayed, unavailable, or restricted; quote and fetch times are shown separately. Unknown feed delay is never labeled streaming. Quotes older than 3 minutes are marked old, including closed markets.

Google News RSS headlines are limited to the previous day, filtered toward Reuters/AP/FT and deduplicated. Headlines may be English. Article content and event time are not independently verified. Source publication time is displayed.

Movement notices compare consecutive fresh samples with a 0.5% threshold, not predictions. Closing/hiding the tab stops further browser requests; an in-flight server fetch can complete. Cache is per process.

No subscription or new host is provisioned. Existing hosting/chat charges remain; assistant chat still uses its existing billable AI tools. Review provider terms and licensed data before relying on the screen for trading.

Tests: python -m unittest -v test_market (mock AI, browser startup and background threads; no paid API calls). External feeds were also smoke-tested separately. Production verification still requires authenticated access.
