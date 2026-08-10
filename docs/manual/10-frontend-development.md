# 10 — Frontend Development

How the Vue dashboard and the TypeScript packages are built, and how to
extend them. All paths relative to `apps/edge-web/` and
`packages/typescript/`.

## Layered architecture

```text
View (pages/*.vue)
  → Composable (composables/*.ts) / Pinia Store (stores/*.ts)
      → Service facade (services/*.ts)
          → ApiClient interface (packages/typescript/api-client/src/edge/ApiClient.ts)
              → MockApiClient.ts (dev/tests) | HttpApiClient.ts (real FastAPI)
                  → validators (validate.ts) + generated types (generated/api.ts)
```

| Layer | Location | Responsibility |
|---|---|---|
| Pages | `src/pages/*.vue` | Route targets; page-local data via `getApiClient()`/services; own refs (e.g. `ReviewView` keeps `items`, `nextCursor`, `requestGeneration`) |
| Components | `src/components/` | Reusable UI with typed props/emits; delegate logic to composables |
| Composables | `src/composables/` | Extracted, unit-testable state machines (`useReviewPanel`) |
| Stores (Pinia) | `src/stores/` | Shared cross-page state (`session`, `runtime`, `alerts`, `inspection`) |
| Services | `src/services/` | Domain facades; pages depend on these, never on a concrete client |
| Client factory | `src/services/client.ts` | Selects Mock vs Http via `VITE_API_MODE`; singleton; cross-origin token handling; media blobs; WS URL + ticket |
| api-client | `packages/typescript/api-client/src/edge/` | The single contract the dashboard depends on |

## Mode selection and auth

- `VITE_API_MODE`: `mock` (dev default) or `http` (production; a production
  build without `http` **throws** — enforced in `vite-mode.ts` and by a Vite
  plugin).
- `getApiClient()` returns a lazy singleton: `HttpApiClient` in http mode,
  `MockApiClient` otherwise.
- Auth: same-origin deployments exchange the token once via
  `createViewerSession(token)` → `POST /api/v1/auth/session` → HttpOnly
  cookie (`viewerToken = null` afterwards); cross-origin dev keeps the token
  **in memory only** and attaches it per request.
- `loadMediaBlobUrl(url)` refuses foreign origins; cross-origin media is
  fetched with the token and rendered as blob URLs; same-origin clips keep
  raw URLs so `Range` works.
- WebSocket: `requestRuntimeTicket()` → `POST /api/v1/ws/runtime/ticket`; the
  ticket is sent as the negotiated subprotocol (never in the URL), re-issued
  per reconnect.

## The operator workflow stays mock

`services/inspectionService.ts` keeps `const operatorWorkflow = new
MockApiClient()` — confirm/continue/manual/current-inspection always hit the
mock because the server has no such endpoints (they 404). Read-only views
route through `getApiClient()` (real data in http mode); `getStatistics`
drops the mock-only `line` filter in http mode (the server rejects it with
400). `OperatorDashboard.vue` shows a "mock demonstration" banner and hides
action buttons in http mode.

## Route table (`src/router/index.ts`)

All routes are lazy-loaded; guard is meta-driven (`requiresAuth`, `admin`).

| Path | View | meta |
|---|---|---|
| `/` | OperatorDashboard | requiresAuth |
| `/live` | LiveInspection | requiresAuth |
| `/history` | HistoryView | requiresAuth |
| `/review` | ReviewView | requiresAuth |
| `/traceability/:sn` | TraceabilityView | requiresAuth |
| `/images/:id` | ImageViewer | requiresAuth |
| `/statistics` | StatisticsView | requiresAuth |
| `/device` | DeviceStatus | requiresAuth |
| `/inspections` | InspectionsView | requiresAuth |
| `/inspections/:id` | InspectionDetailView | requiresAuth |
| `/uploads` | UploadsView | requiresAuth |
| `/health` | HealthView | requiresAuth |
| `/configuration` | ConfigurationView | requiresAuth + admin |
| `/logs` | LogsView | requiresAuth + admin |
| `/dev` | DevToolsView | requiresAuth + admin |
| `/login` | LoginView | public |
| `/forbidden` | AccessDenied | public |

Nav links in `App.vue`; admin links gated by
`!isHttpMode() || (session.authenticated && session.admin)`.

## Adding a new page end-to-end

1. **Router**: add the route with `name`, `meta: { requiresAuth: true }`
   (`admin: true` for admin pages), lazy component import. The guard needs
   no change. Add a nav link in `App.vue` if it belongs in the shell.
2. **View**: create `src/pages/YourView.vue`; fetch via `getApiClient()` or a
   service; keep business logic in a composable or store (the `ReviewPanel`
   pattern).
3. **Service** (optional): add a method to `inspectionService.ts`/
   `deviceService.ts` with a typed return delegating to `getApiClient()`.
4. **ApiClient interface** (`packages/typescript/api-client/src/edge/
   ApiClient.ts`): add the method signature with a JSDoc citing the design
   doc.
5. **Mock implementation**: deterministic data + mirrored validation/error
   codes (see parity below).
6. **HTTP implementation**: implement with the private `#request(path, init?,
   validator?)` helper (builds `/api/v1{path}`, attaches bearer,
   `credentials: "same-origin"`, parses `Problem` into `ApiError`, runs the
   validator).
7. **Validators** (`validate.ts`): add a `validate*` function checking every
   field the UI reads and register it in `validators`. Helpers:
   `expectRecord`, `hasString`, `hasNumber`, `hasBoolean`, `hasOneOf`,
   `hasArray`, `hasRecord`, `pageOf`.
8. **Types**: add hand types to `types.ts` (synced with the Pydantic models;
   copy the `ReviewRecord`/`SubmitReviewRequest` block) if new payload shapes
   appear.
9. **Contract regeneration** (after backend changes):
   ```bash
   uv run python scripts/generate-edge-openapi.py
   pnpm --filter @assemblyvision/api-client generate:types
   ```
   CI fails on drift for both artifacts.
10. **Tests**: unit (Vitest) + e2e (Playwright), patterns below.

## Mock/server parity

The mock mirrors the server's request validation and error codes so UI error
handling behaves identically in both modes. Example: review dispositions are
defined in three mirrored places — `useReviewPanel.ts` (UI gating), the
mock's `allowedDispositions()` (rejects with `422 REVIEW_DISPOSITION_
INVALID`), and `validate.ts` `validateReviewRecord` (`hasOneOf` over the same
enum on the HTTP response path). `MockApiClient.submitReview` enforces
reviewer non-empty, `INCONCLUSIVE` requires reason, supersede ownership
(`409 REVIEW_CONFLICT`), unknown inspection (`404`). When adding endpoints,
mirror the server's 400/404/409/422 codes exactly.

## Canonical example: review workflow

- `ReviewView.vue` (queue): `getApiClient().listReviewQueue({ business_result,
  reviewed, cursor, limit })`, guarded by a `requestGeneration` counter so
  stale responses are dropped; rows link to `/inspections/:id`.
- `InspectionDetailView.vue` mounts `<ReviewPanel :inspection-id
  :business-result :internal-decision>`.
- `ReviewPanel.vue` destructures `useReviewPanel(...)`; renders disposition
  select (from `allowed`), reviewer, reason, note; submit gated by
  `canSubmit` (history loaded, no error, form valid); shows append-only
  history.
- `useReviewPanel.ts`: `load()` fetches history (failure blocks submission);
  `submit()` calls `getApiClient().submitReview(...)` then reloads history.
- `HttpApiClient.submitReview` POSTs `/api/v1/inspections/{id}/reviews` with
  `{disposition, reviewer, reason, note, supersedes_review_id,
  component_corrections}`.
- `MockApiClient.submitReview` validates identically, appends a
  `ReviewRecord`, and logs.

## Shared UI (`packages/typescript/ui`)

- `DetectionViewer.vue` — contain-fit letterboxed preview; renders only boxes
  whose `frameId === currentFrameId`; `STALE FRAME` badge after
  `staleAfterMs`; overlay colors product `#00c853` / component `#ff5252` /
  roi `#2196f3`.
- `StatusBadge.vue` — color + icon + text (never color-only);
  `statusPresentation` tones success/danger/warning.
- `format.ts` — `formatBytes`, `formatIsoTime`, `formatLatency`,
  `reasonCodeLabel` (falls back to raw code).
- `geometry.ts` — `containFit`, `mapBoxToView`, `boxToRect`,
  `clipToImageRect` (source-coordinate → view mapping).

## Edge desktop (`apps/edge-desktop`)

- Electron main: loads built `edge-web/dist/index.html` (production) or the
  Vite dev server (`ELECTRON_DEV=1`); `ELECTRON_KIOSK=1` → fullscreen,
  no menu.
- Hardening: `contextIsolation: true`, `sandbox: true`,
  `nodeIntegration: false`; `setWindowOpenHandler` denies in-app navigation
  (external http(s) → OS browser); `will-navigate` restricted to localhost
  dev / `file:` production.
- Preload exposes `window.assemblyVisionDesktop = { platform, versions }`.

## Testing (details in `11-testing-and-quality-gates.md`)

- Unit: Vitest with `vi.hoisted` + `vi.mock` of `../src/services/client`
  (composable tests), `vi.stubEnv("VITE_API_MODE", ...)` + `vi.resetModules`
  (mode tests), `setActivePinia(createPinia())` (store tests).
- E2E: Playwright; `smoke`/`operator`/`theme` specs run against the Vite dev
  server in mock mode; `served-api.spec.ts` spawns the real Python service
  (`uv run assemblyvision serve --api-token test-edge-token ...`), logs in
  through `/login`, and asserts real data + the review flow.
