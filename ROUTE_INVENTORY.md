# DEAN route and data inventory

Audited from the current `main` source on 2026-11-19. This is an inventory only; it does not modify the live service.

## Flask routes in app.py

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Main DEAN interface |
| GET | `/login` | Login page |
| POST | `/login` | Login submission |
| POST | `/api/logout` | Logout |
| POST | `/api/chat` | Main chat |
| POST | `/api/external/chat` | External chat integration |
| GET | `/api/reminders/due` | Due reminders |
| GET | `/api/version` | Version/release information |
| GET | `/health` | Health and self-test |
| GET | `/browser-test` | Browser test page |
| GET | `/browser-start` | Start browser |
| GET | `/browser` | Shared browser UI |
| GET | `/api/browser/status` | Browser status |
| GET | `/api/browser/frame` | Browser frame |
| POST | `/api/browser/navigate` | Navigate browser |
| POST | `/api/browser/click` | Browser click |
| POST | `/api/browser/scroll` | Browser scroll |
| POST | `/api/browser/type` | Type into browser |
| POST | `/api/browser/key` | Send browser key |
| POST | `/api/browser/reload` | Reload browser page |
| POST | `/api/speech` | Text-to-speech |
| POST | `/api/live/token` | Realtime voice token |
| POST | `/api/live/log` | Realtime voice diagnostics |
| POST | `/api/feedback` | Feedback |
| GET | `/tiktok/connect` | TikTok OAuth start |
| GET | `/tiktok/callback` | TikTok OAuth callback |
| GET | `/api/tiktok/status` | TikTok connection status |

Some browser and chat routes are protected by login/CSRF decorators. Verify each authorization rule during migration; do not assume all routes are public or all are protected.

## Life journal routes in life.py

| Method | Path | Purpose |
|---|---|---|
| GET | `/life` | Life journal UI |
| GET | `/api/life/dashboard` | Dashboard data |
| POST | `/api/life/tasks` | Add task |
| PUT/PATCH | `/api/life/tasks/<id>` | Update task (verify actual decorator/method) |
| DELETE | `/api/life/tasks/<id>` | Delete task |
| POST | `/api/life/reminders` | Add reminder |
| PATCH | `/api/life/reminders/<id>` | Update reminder |
| POST | `/api/life/areas` | Add life area |
| POST | `/api/life/goals` | Add goal |
| PUT/PATCH | `/api/life/goals/<id>` | Update goal (verify actual decorator/method) |
| DELETE | `/api/life/goals/<id>` | Delete goal |
| POST | `/api/life/checkins` | Add progress check-in |
| POST | `/api/life/summary` | Add summary |
| GET | `/share-review` | Review-link page |
| POST | `/share-review` | Create review link |
| GET | `/review-access/<token>` | Consume review access token |

## SQLite/PostgreSQL tables found in source

From `app.py`:
- `messages`
- `memories`
- `tasks`
- `reminders`
- `login_attempts`
- `action_requests`
- `releases`
- `feedback`

From `life.py`:
- `life_areas`
- `life_goals`
- `life_checkins`
- `life_summaries`
- `life_review_tokens`

The exact columns, foreign-key behavior, and migration compatibility must be validated from the complete DDL before building import/export. Do not infer a schema from this list alone.

## BenFit data already in the current code

The life journal source contains a BenFit exercise/workout UI and uses browser `localStorage` keys:
- `dean_benfit_exercises`
- `dean_benfit_workouts`

These records are not part of the SQLite/PostgreSQL tables above. They may be stored in the browser profile on the device where the page was used. A server-side database export will not capture them. The migration must include a separate BenFit export/import path and should preserve the existing keys until the user verifies the new app.

## AI and browser dependencies

- OpenAI SDK is imported and initialized at app startup; missing OpenAI key currently raises an exception before the app can start.
- Chat, automatic memory extraction, web search, speech, realtime token issuance, and self-test use the OpenAI client.
- Gemini key/provider configuration exists in environment parsing, but this source review has not yet established that Gemini can fully replace every OpenAI-specific call.
- Persistent browser startup is initiated at app startup. Browser failure should be isolated from the core application.
- TinyFish browser support is optional and depends on its API key.
- Browserless Chromium is a separate Render service described in `render.yaml`.

## Security scan status

A quick scan of the current `app.py` and `life.py` blobs found no obvious hard-coded credential patterns (OpenAI project keys, Google API keys, GitHub classic tokens, private-key headers, or long literal values assigned to common secret variable names).

This is not a complete secrets audit:
- Git history has not yet been scanned.
- Other files and all branches have not yet been scanned.
- GitHub code-search returned no indexed results, which is not proof of absence.
- Because the repository is public, any discovered credential must be rotated immediately.
