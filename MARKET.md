# Market room

Private /market dashboard with a selectable watchlist, reference intraday charts, source quote timestamps, explicit freshness labels, headlines, start/stop controls and responsive Hebrew layout.

No automated trades, account connection, browser-session sharing, paid subscriptions or AI calls in this dashboard. Existing chat and hosting charges remain. Public Yahoo Finance and Google News data can be delayed or blocked; no streaming or completeness guarantee. Cash indices, shares and commodity futures are not Plus500 CFD quotes. Headlines remain in their source language and article/event-time verification is not provided.

## Shared view

Existing DEAN database stores one latest delivered snapshot per browser tab in market_monitor_views. The browser acknowledges successful rendering with a CSRF-protected POST, saving the selected symbol and monitoring/paused/stopped state. The last acknowledged payload remains available if a newer delivery was not rendered. The payload comes from the server, not client-provided prices. Saved timestamps indicate past observations, not current browser activity. A stale snapshot must not be described as live.

/api/market/shared-state is authenticated. The authorized assistant can read the last acknowledged snapshot through the connected Render database, without requesting a screen copy. This shares only dashboard datasets and selected assets, not other Safari tabs, broker positions or the contents of opened external articles. A page refresh is required to activate sharing after this upgrade.

Background tabs pause polling. Browser close notifications are best effort; viewed_at must be checked before making activity claims. No 24/7 worker is added. Prices refresh on demand with a process-local 60-second cache; headlines use five minutes.

## Checks

python -m unittest -v test_market

Twelve tests cover authentication, CSRF, cache, quote validation, chart samples, provider failures and server-backed render acknowledgments, including rejection of stale snapshot IDs and client price injection. AI/browser background work is mocked and no paid API calls run during tests. A separate provider smoke test returned 201 actual S&P chart points. No production authenticated view is assumed merely because a deploy is live.
