# 16. Edge Dashboard

## 16.1 Purpose and Users

The edge dashboard is a Vue 3 and TypeScript web application served by the local edge service. It supports line operators and maintenance staff without participating in the inspection decision path. Inspection continues when the browser is closed, the dashboard crashes, or the central server is unreachable.

The dashboard consumes the edge contracts in [REST API and Events](15-rest-api-and-events.md) and generated types from [Data Model and Database](14-data-model-and-database.md). Monorepo placement is defined in [Monorepo and Code Organization](18-monorepo-and-code-organization.md).

## 16.2 Design Principles

1. Show the latest safety-relevant result at a glance; do not hide NG reasons behind navigation.
2. Distinguish inspection readiness from central connectivity. An offline central server does not imply inspection failure.
3. Never infer system state solely from a WebSocket event; reconcile from REST after reconnect or a sequence gap.
4. Preserve usable local history and controls while disconnected from central services.
5. Require explicit confirmation and a reason for pause, resume, reconnect, retry, or configuration changes.
6. Use text, iconography, and color together. Red/green alone is not sufficient.
7. Avoid displaying a high-confidence detection as proof of overall OK; the final deterministic decision is authoritative.

### 16.2.1 Theme System

The dashboard provides a persisted, local UI preference with three professional
themes. Theme choice changes visual tokens only: routes, component structure,
layout hierarchy, spacing scale, typography scale, interaction patterns, safety
labels, and API behavior remain identical. Density, colors, borders, shadows,
radius, and visual atmosphere vary per theme by design.

| Theme | Intended environment | Visual characteristics |
|---|---|---|
| Industrial Minimal (default) | Shop-floor HMI and maintenance terminals | Sharp rectangular surfaces, compact density, strong separators, restrained elevation, neutral steel palette |
| Modern Light | Engineering review and management workstations | Bright surfaces, moderate radius, measured whitespace, subtle elevation, enterprise-blue accent |
| Modern Dark | Long-running monitoring and control rooms | Graphite surfaces, high contrast text, subdued borders, readable non-neon status indicators |

CSS custom properties are the single token source for backgrounds, surfaces,
text, borders, focus, semantic status colors, density, radius, and Element Plus
variables. ECharts consumes the active token palette explicitly because canvas
charts do not inherit CSS variables. The selected theme is stored locally and
does not affect inspection decisions, audit records, uploads, or device state.
Semantic meaning remains stable in every theme: green means normal/OK, red
means NG/alarm, amber means warning/uncertain, and blue means informational.
Color always supplements text and iconography rather than replacing it.

### 16.2.2 Interface Language

The dashboard UI is internationalized with English as the source locale and
default, plus Simplified Chinese (Mainland China, `zh-CN`), Traditional Chinese
(Hong Kong, `zh-HK`), and Japanese (`ja`). Each message key is the English text
itself — `t("History")` — so code remains readable and the locale catalogs
(`src/i18n/locales/`) translate the same keys. Missing keys fall back to
English via vue-i18n's fallback locale; message values must escape the
linked-message prefix (`{'@'}`) and plural pipe syntax when the English text
contains those characters.

The build-time default language is configurable through `VITE_DEFAULT_LOCALE`
in `.env.development` / `.env.production` (`en | zh-CN | zh-HK | ja`); an
unset or unsupported value falls back to English. Operators switch the live
language from a globe-icon dropdown in the header; the selection is persisted
in browser storage (`assemblyvision.edge.locale`) and always wins over the
build default. The chosen locale drives both the dashboard strings and the
Element Plus component locale through `el-config-provider`. The document
`lang` attribute follows the locale so screen readers and browser translation
behave correctly. Language choice never affects inspection decisions, audit
records, uploads, or device state.

## 16.3 Information Architecture

| Route | Primary purpose | Roles | Data source |
|---|---|---|---|
| `/` | Live inspection and current operational state | Viewer, operator | Status REST snapshot and runtime WebSocket |
| `/inspections` | Search recent local records | Viewer | Local inspection REST API |
| `/inspections/:id` | Review evidence, overlays, versions, and media | Viewer | Inspection/media REST APIs |
| `/review` | Optional human review queue and dispositions | Viewer | Review REST API (design 24, ADR-016) |
| `/uploads` | Queue state, failures, and manual retry | Viewer; operator retries | Upload REST API and events |
| `/health` | Camera, model, disk, network, database, and service health | Viewer | Device/camera/health APIs |
| `/configuration` | Effective configuration and permitted local overrides | Edge administrator | Configuration APIs |
| `/logs` | Bounded local structured logs | Edge administrator | Log API |

The top bar always displays device code, line label if configured, inspection state, local clock, central connectivity, disk warning, and authenticated user. The application must remain navigable if preview streaming is unavailable.

## 16.4 Live Inspection Screen

### 16.4.1 Layout

Desktop uses a dominant camera/evidence pane and a fixed-width decision pane. At 1280 pixels and above, both are visible without vertical scrolling. Tablet/mobile stacks decision first, then evidence, then diagnostics; pause/resume remains reachable but is not a floating control that can be triggered accidentally.

The screen includes:

- Camera preview with contain scaling, source resolution, capture timestamp, and stale-frame marker.
- Optional product and component bounding boxes mapped from source coordinates, never pre-scaled server coordinates.
- Final `OK`, `NG`, or `UNCERTAIN` panel with inspection ID, barcode, product type, processing latency, and completion time.
- Required-component matrix: present, missing, uncertain, best confidence, supporting frame count, and policy reason.
- Readiness strip for camera, model, rule, local database, disk, and inspection engine.
- Connectivity strip separating local API, network interface, DNS/central reachability, and upload backlog.
- Recent result rail showing at least the last ten inspections, with keyboard-accessible detail links.

### 16.4.2 Result Presentation

`OK` may use green but includes the word “OK” and a check icon. `NG` uses red, the word “NG,” an alert icon, and the missing/uncertain component names. `UNCERTAIN` uses amber and states whether the physical handling path treats it as NG. New results use a brief non-blocking transition; animations must respect reduced-motion preferences.

Barcode failure, unknown product, unusable frames, model failure, and missing component are separate reason codes. The UI must not collapse all NG outcomes into “component missing.”

### 16.4.3 Preview Transport

Use a bandwidth-limited JPEG/MJPEG or WebRTC preview only if justified by latency requirements. Do not send full production frames through JSON WebSocket messages. Overlay events carry source dimensions and boxes; the UI discards overlays whose frame ID does not match the displayed preview frame. Preview loss never changes the inspection engine state.

Until the WebSocket runtime channel lands, the dashboard live view consumes
the per-instance REST preview `GET /api/v1/camera/{instance_id}/preview`
(rate-limited latest-frame JPEG, ADR-013). The WebSocket milestone reuses the
same frame pipeline and supersedes this stopgap without changing the
inspection engine.

## 16.5 Inspection History and Detail

History defaults to newest first and supports business result, internal decision, barcode, product, and bounded date filters. Search is debounced and server-side; cursor pagination prevents loading the full local database. A row displays completion time, business result, internal decision detail, barcode, product, reason summary, latency, upload state, and model/rule versions.

The detail page contains:

- Immutable identity and capture timestamps.
- Decision reason codes and per-component aggregated evidence.
- Product and component detection overlays with toggles and accessible component list.
- Key frame, product ROI, annotated image, and clip tabs only when media exists.
- Frame-quality indicators and source/full-frame coordinate metadata.
- Model, rule, and product configuration version identifiers.
- Upload task state and last failure without exposing credentials or stack traces.

Purged media displays metadata and purge reason rather than a broken image. Video uses range requests and provides a static fallback key frame.

## 16.6 Upload Queue

The queue page groups `PENDING`, `IN_PROGRESS`, `RETRY_WAIT`, `PERMANENT_FAILURE`, `CANCELLED`, and `SUCCEEDED` counts. Default rows show unfinished tasks, next attempt, attempt count, object kind, inspection link, bytes, and sanitized error code. The dashboard explains that retries continue without the page being open.

Manual retry is enabled only for retry/dead-letter tasks, requires confirmation and reason, and sends an idempotency key. It does not create a second task. Bulk retry is deferred until operational evidence shows it is needed; unbounded bulk retry can overload the central server after an outage.

## 16.7 Health and Alerts

| Condition | UI state | Required operator guidance |
|---|---|---|
| Camera disconnected | Critical, inspection not ready | Check cable/power; administrator may request reconnect |
| Model or rule unavailable/incompatible | Critical, no new windows | Show active/desired versions and escalation instruction |
| Disk below warning threshold | Warning | Show free bytes, retention activity, and estimated risk without invented time remaining |
| Disk below stop threshold | Critical | State whether capture is paused; never silently discard required evidence |
| Central unreachable | Degraded, not inspection-failed | Show offline duration and persistent queue count |
| Queue dead-letter present | Warning | Show task/error and retry/escalation path |
| Clock drift detected | Warning or critical by threshold | Show measured drift and time-source check |
| Inspection paused | Prominent neutral/amber state | Show actor, reason, and time where available |

Alerts have stable codes, severity, first/last observed timestamps, and active/cleared state. Browser toast notifications supplement but never replace persistent status.

## 16.8 Local Configuration

The page separates centrally managed values, local overrides, and effective values. Managed fields are read-only. Editable MVP fields should be limited to explicitly approved operational settings such as preview preferences or allowed local storage thresholds; detector thresholds and decision rules should normally be centrally versioned.

Configuration workflow:

1. Load effective configuration and revision.
2. Edit a draft with field-level units, ranges, and descriptions.
3. Validate through the API without activation.
4. Show the semantic difference and effects requiring restart or inspection pause.
5. Require administrator confirmation and reason.
6. Submit with `If-Match`; on conflict, reload and reapply deliberately.
7. Display activation result and audit/event identifier.

Never offer arbitrary JSON editing to operators in production.

## 16.9 Pause and Resume Safety

Pause means stop opening new product windows. The API owns behavior for an active window: finish safely or mark aborted according to configured policy. The confirmation identifies the consequence and captures a reason. Resume remains disabled until camera, model, rule, database, and disk preconditions pass. The UI displays API rejection detail and must not optimistically show `READY` before confirmation.

Emergency machine stopping is a factory safety-control concern and must not be represented as a web button unless integrated with validated machinery controls. The dashboard pause is an application-level inspection control, not an emergency stop.

## 16.10 State and Data Flow

- Vue Router controls route authorization and deep links.
- Pinia stores only session, effective permissions, runtime snapshot, alert state, and lightweight UI preferences.
- Historical queries remain page-local/server-driven; do not mirror the inspection database into Pinia.
- A generated OpenAPI client handles typed REST. A single WebSocket service validates envelopes and dispatches resource invalidations.
- On startup: fetch session, permissions, status, and current inspection; then connect WebSocket.
- On reconnect or sequence gap: mark data stale, refetch snapshots, then clear stale state.
- Use exponential reconnect backoff with jitter and an upper bound. Browser reconnect behavior must not affect edge upload retries.

## 16.11 Failure, Loading, and Empty States

Every pane defines loading, no-data, stale-data, authorization-denied, and service-error states. Last-known status may remain visible with an explicit “last updated” timestamp; it must not look current. Failed commands retain form input and request ID. Missing preview does not blank the result panel. The service worker must not cache authenticated API responses; static assets may be cached for local resilience with version-safe updates.

## 16.12 Accessibility, Performance, and Security

- Meet WCAG 2.1 AA for keyboard operation, focus, contrast, labels, dialogs, tables, and non-color status indicators.
- Virtualize only tables proven large; cursor pagination is the first control.
- Lazy-load video and advanced viewer code. Keep initial live screen assets small enough for the target edge hardware.
- Sanitize filenames and log text, prohibit raw HTML, and use a restrictive Content Security Policy.
- Use secure, HTTP-only, same-site cookies where sessions are used; protect mutations against CSRF.
- Do not place tokens, barcodes, or media URLs in analytics. The local dashboard should not depend on third-party CDNs.

## 16.13 Testing and Acceptance

Vitest covers stores, reason-code rendering, coordinate transforms, permissions, and reconnect reconciliation. Component tests cover all result/health states and keyboard behavior. Playwright exercises live result arrival, stale connection recovery, history/detail, purged media, queue retry, configuration conflict, pause/resume rejection, and offline-central operation. Visual tests use representative 4:3 images and long component/barcode strings.

Acceptance checks include:

- Inspection remains active with the dashboard closed and central disconnected.
- A WebSocket gap is reconciled without losing the latest result.
- NG reasons and missing components are visible without opening a modal.
- Bounding boxes remain aligned under resize and full-screen modes.
- Unauthorized controls are unavailable and server authorization still rejects direct calls.
- The live view remains usable at the agreed industrial display resolution and on a narrow maintenance device.

## 16.14 MVP and Later Scope

MVP includes live status/latest result, recent history/detail, health, queue visibility/manual retry, and pause/resume if operationally approved. Local override editing and logs may be administrator-only late-MVP features. Later additions may include WebRTC preview, kiosk packaging/Tauri, alert acknowledgement workflow, guided camera calibration, and richer multi-frame evidence playback. None is required for the static train-and-inspect MVP.

## 16.14.1 Developer Tools (`/dev`)

A `/dev` route groups developer-mode tools (ADR-014), including a **Test** tab
that takes a photo (mobile OS camera via file capture), uploads an image, or
uploads a short video and shows the inspection decision immediately, with the
product bounding box overlaid client-side on the source image and a per-frame
summary table for videos. A **Logs** tab reuses the bounded log view, and
future tools (camera preview, config/DB inspection) may join the same page.
The tools require `VITE_API_MODE=http` and a `serve` run with
`--enable-web-test`; otherwise the page explains how to enable them. The dev
tools never stream video and are not a production acquisition path.

## 16.15 Open Questions and Validation Required

- Confirm display sizes, browser, kiosk mode, touch/keyboard use, language, and accessibility needs at the line.
- Confirm whether application pause/resume is operationally allowed and how an active product is handled.
- Confirm acceptable preview frame rate, latency, and bandwidth on the edge computer.
- Confirm which configuration fields may be overridden locally and which roles may do so.
- Validate warning/stop disk thresholds and operator recovery instructions.
- Confirm whether local authentication must integrate with a customer identity system while offline.
