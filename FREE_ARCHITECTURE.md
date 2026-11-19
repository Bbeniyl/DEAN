# DEAN — zero-required-spend target architecture

Date: 2026-11-19  
Decision status: proposed for implementation in the isolated migration branch only.

## Goal
Keep DEAN usable for one iPad owner without requiring a monthly subscription or a paid AI API. The core journal, tasks, memories, goals, workout records, and backups must not depend on a remote AI model or a continuously running paid server.

## Proposed layers

### 1. PWA frontend
- Static Hebrew RTL app hosted on Cloudflare Pages.
- Installable from Safari to the iPad Home Screen.
- Service worker caches the app shell so the interface can reopen offline.
- IndexedDB stores structured application data locally; do not use localStorage as the primary database.
- Import/export uses a versioned JSON backup format.
- Backup file can be saved by the user into Files/iCloud Drive. Encryption should be offered before export because the data is personal.
- Existing BenFit localStorage keys must be imported and verified before they are retired.

### 2. Core application logic
Core features run locally and do not call an AI model:
- create/edit/delete tasks and reminders;
- add/edit memories;
- life areas, goals, check-ins, and summaries;
- BenFit exercises and workout history;
- search/filter local records;
- export/import and restore;
- local notifications while app is open.

No AI call, browser failure, or network outage may block these features.

### 3. Optional encrypted cloud backup/sync
If a cloud copy is wanted, use one Cloudflare Worker API and D1. The client encrypts the backup payload before upload; the server stores ciphertext and metadata only. Authentication and account recovery must be designed before enabling sync. Do not store an unencrypted life-history database on a public or shared endpoint.

Cloudflare official limits checked 2026-11-19:
- Workers Free: 100,000 requests/day; 10 ms CPU per invocation.
- Static asset requests: free and unlimited.
- D1 Free: 5 million rows read/day, 100,000 rows written/day, 5 GB storage across the account, up to 10 databases, and 500 MB maximum per database.
- D1 Free point-in-time Time Travel retention: 7 days.
- Exceeding free D1 daily row limits causes D1 queries to fail until the daily reset; it does not itself delete stored data.
- Workers Free supports up to 5 Cron Triggers per account.
- Pages Functions share the Workers Free request quota. Keep the static frontend separate from API functions so normal static asset traffic does not consume Worker requests.

Official sources:
- Workers limits: https://developers.cloudflare.com/workers/platform/limits/
- Workers pricing and D1 quotas: https://developers.cloudflare.com/workers/platform/pricing/
- D1 database size/storage limits: https://developers.cloudflare.com/d1/platform/limits/
- Pages Functions/static asset pricing: https://developers.cloudflare.com/pages/functions/pricing/

No paid Workers plan, paid domain, paid database, or paid add-on is part of this proposal.

### 4. Reminders and notifications
- Foreground reminders can be evaluated locally while the app is open.
- Background push is technically supported by iPadOS Home Screen web apps from iPadOS 16.4 onward. It requires user permission, a service worker, a push subscription, and a server that sends Web Push.
- A single scheduled Worker can check due reminders and send Web Push. This must be implemented only after testing iPadOS behavior and the free Cron Trigger limits.
- Do not promise delivery if the device is offline, notifications are disabled, or the push provider rejects the subscription.

Apple documentation: https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers

### 5. AI and advanced integrations
- No-AI mode is the default and must work indefinitely without any API key.
- Gemini can remain an optional, user-enabled provider for ordinary chat only, subject to free-tier availability, quotas, and its data-use terms.
- OpenAI speech/realtime/search features must not be required for app startup. Use iPad/browser speech capabilities where supported and disclose differences in quality and availability.
- Browser automation, TikTok, external web search, and market data are optional integrations. Disable them cleanly when credentials or quotas are unavailable.
- Never send private memories, family details, or journal content to a free AI provider by default. Ask the user to opt in and disclose the provider's data-use terms.

## Why not simply move the current Flask app to Workers?
Cloudflare Workers is a JavaScript/TypeScript runtime, while the current server is a large Flask/Python app. A direct port would require a broad rewrite of routing, SQL access, auth/session handling, browser automation, and provider SDKs. A local-first PWA gives immediate no-cost core functionality while allowing the existing backend to remain untouched until the new version is complete.

## Migration safeguards
- Build under `dean-free-migration-audit`; do not change `main`.
- No deploy to the live Render service during discovery.
- No destructive changes to the old app, localStorage, database, or Render resources.
- The live Render SQLite database and BenFit localStorage are separate data sources and require separate verified exports.
- Keep import idempotent and versioned; repeated import must not create duplicate records.
- A restore test on a clean browser profile is mandatory.
- No cutover until the user approves after reviewing the tested replacement.
