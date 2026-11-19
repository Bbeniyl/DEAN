# DEAN — Free Migration Audit

Date: 2026-11-19  
Status: discovery and preservation phase. No production service, environment variable, database, or main branch has been changed.

## Safety rules
- Keep `main` and the live Render service untouched during migration work.
- Work only on `dean-free-migration-audit` until a tested replacement is ready.
- Do not delete Render services, databases, disks, secrets, or repository history.
- Do not expose API keys, passwords, session secrets, or database URLs.
- Export and verify all user data before any redeploy or migration that could restart the live service.
- Do not enable paid plans or create paid resources without explicit user approval.

## Repository inventory observed
- `app.py` (~141 KB): Flask application, chat, messages, memories, tasks, reminders, approvals, browser integration, and API routes.
- `life.py` (~112 KB): separate life-journal dashboard and routes.
- `index.html` (~14.6 KB): Hebrew RTL life-journal frontend.
- `life_world.py`: immersive/3D journal world.
- `market.py`: market-related functionality.
- `persistent_browser.py`: persistent browser connection.
- `public/`: small static pages including privacy and terms.
- `backups/life.py.2026-11-18.bak`: existing source backup.
- `browserless-render/`: Browserless Chromium service definition.
- `render.yaml`: currently describes the browser service, not a complete replacement deployment for the DEAN web app.
- `requirements.txt`: Flask, OpenAI SDK, Gunicorn, psycopg, requests, websocket-client.

Repository visibility: public. A dedicated secrets/history audit is required before any further publication or migration. Never add credentials to this repository.

## Live Render observations (2026-11-19)
- Web service `dean-agent` is on the Free plan and is not suspended.
- Service deploys/builds completed successfully after the recent code and environment changes.
- No PostgreSQL instances were returned for the current Render workspace.
- Recent service events queried since 2026-09-27 showed no plan-change, suspension/resume, or disk create/update/delete events.
- App startup logs previously showed a DNS resolution failure for the configured PostgreSQL hostname. The app catches this and sets `DATABASE_URL` empty.
- With no reachable PostgreSQL URL, the code uses SQLite at `/tmp/dean.sqlite3`. This is ephemeral storage on Render and must not be treated as durable.
- The current `app.py` requires an OpenAI API key at import/startup and creates an OpenAI client unconditionally. Automatic memory extraction and web search also call the OpenAI client.
- The service health check previously showed the model API and speech TTS passing, but browser connectivity failing with HTTP 429. A browser failure must not make core journal/task functions unavailable.

## Important correction to the migration design
A browser-only or local-only redesign is not automatically a full replacement for the existing DEAN. The existing Flask application and life journal contain substantial functionality. Preserve and map each route, data table, and user workflow before replacing any part.

A browser-based PWA can provide offline UI and local-first storage, but it does not by itself provide reliable push notifications, secure multi-device sync, or automatic backups. Those must be designed and tested separately. Do not promise that an iPad browser can deliver all background reminders when the app is closed.

## Migration sequence

### Phase 0 — preserve and inspect
1. Keep this audit branch separate from `main`.
2. Inventory all repository paths, routes, templates, static assets, database tables, and integrations.
3. Inspect the Git history and public repository for accidentally committed secrets. If any credential is found, treat it as compromised and rotate it; do not merely delete the visible line.
4. Determine whether the currently running Render instance still has a live `/tmp/dean.sqlite3` file and whether a safe export endpoint or one-time export method can be added without restarting the service.
5. Export the live database only through an authenticated, access-controlled method. Verify row counts and a restorable backup before any redeploy. Never print database contents or secrets into logs.
6. Determine whether a prior PostgreSQL instance or backup can be restored. Do not create a new paid database.

### Phase 1 — functional specification
Document all existing routes and user-facing flows for:
- login/session and account security;
- chat and conversation history;
- memories and memory retrieval;
- tasks and completion/reopen/delete;
- reminders and notification state;
- approval requests;
- life domains, goals, progress, and journal;
- market information;
- voice input/output;
- browser and web search;
- release notes, feedback, health checks, and exports.

For every feature mark: keep, redesign, optional integration, or retire (only with user approval).

### Phase 2 — architecture for a zero-required-spend baseline
- Keep a no-AI mode as a first-class mode. App startup and all core CRUD operations must work without OpenAI or Gemini credentials.
- Separate AI provider adapters from core business logic. AI failure must never block journal, memory CRUD, task CRUD, or data export.
- Prefer local-first PWA storage for the initial single-device experience, with explicit export/import and versioned backups.
- Add cloud sync only after comparing current free-tier limits, privacy terms, and data portability. Never make a free-tier promise without checking current official limits.
- Treat browser automation, web search, and advanced AI as optional capabilities, not core dependencies.
- Use device-native speech APIs where practical; disclose limitations of browser speech and background operation.
- Design schema migrations and import/export before moving existing user data.

### Phase 3 — implementation in this branch
Build the new app in small, reviewable commits. Do not connect it to the production Render service. Do not change `main`. Add automated tests for persistence, backup/restore, and no-AI operation.

### Phase 4 — acceptance testing
Do not call the migration complete until:
- iPad layout, Hebrew RTL, and home-screen installation are tested;
- every retained screen and route works;
- CRUD works for memories, tasks, reminders, domains, goals, and journal entries;
- data survives app close/reopen and device restart;
- offline behavior is tested;
- export and restore are tested on a clean copy with row counts and content integrity checks;
- AI keys can be absent and AI provider failure does not break core features;
- privacy/security and authorization checks pass;
- notifications are tested separately for foreground and background behavior;
- all external links and integrations are tested.

### Phase 5 — cutover
Only after verified backup, successful acceptance tests, and explicit user approval:
1. choose a deployment target based on current free-tier and privacy terms;
2. deploy the new version separately;
3. import a verified copy of data;
4. compare counts and sample records;
5. switch the user-facing link;
6. keep the old service and repository history available for rollback until the new version is proven stable.

## Current blockers
- No direct safe access has yet been established to the live ephemeral SQLite file.
- No Render PostgreSQL instance is currently listed.
- The actual live environment variable values are intentionally not read or exposed.
- Current public repository history has not yet completed a secrets scan.
- Exact route/table inventory and current frontend/backend coupling still need to be completed.
