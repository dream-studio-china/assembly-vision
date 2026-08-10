# AssemblyVision Developer Manual

> The developer's on-boarding and extension manual for the AssemblyVision
> industrial assembly inspection system. It describes how the code is
> organized, how the real CLI and API behave, how the runtime works
> internally, and how to extend every subsystem — for developers who are
> taking over or adding to this system.
>
> This manual is written for **developers**; for architecture rationale,
> engineering contracts, and operational runbooks use the authoritative
> sources directly (`docs/design/`, `docs/design/decisions/`,
> `docs/contracts/`, `docs/runbooks/`). When documents conflict the
> precedence is: explicit user instruction → accepted ADR → engineering
> contract → architecture design → existing implementation.

## How to use this manual

1. [01-getting-started.md](01-getting-started.md) — clone, setup, run the
   pieces, daily workflow, quality gates.
2. [02-repository-layout.md](02-repository-layout.md) — where every part of
   the code lives.
3. [03-cli-reference.md](03-cli-reference.md) — every CLI command with real
   invocations and exact output.
4. [04-edge-api-reference.md](04-edge-api-reference.md) — every REST/WS
   endpoint with real request/response examples and curl calls.
5. [05-edge-service-internals.md](05-edge-service-internals.md) — how an
   image becomes an inspection record; how `serve` runs live inspection.
6. [06-adding-a-rest-endpoint.md](06-adding-a-rest-endpoint.md) — end-to-end
   recipe for adding a new API endpoint.
7. [07-database-and-persistence.md](07-database-and-persistence.md) —
   SQLite schema, Alembic migrations, repository and outbox patterns.
8. [08-camera-sources-and-vision-core.md](08-camera-sources-and-vision-core.md)
   — the `FrameSource` protocol, ROI engine, model manifests, how to add a
   camera source.
9. [09-training-and-datasets.md](09-training-and-datasets.md) — the dataset
   pipeline, `av-train`, how to train/extend models.
10. [10-frontend-development.md](10-frontend-development.md) — Vue dashboard
    architecture, API client, how to add a page.
11. [11-testing-and-quality-gates.md](11-testing-and-quality-gates.md) —
    test organization, fixture patterns, exact commands, CI.
12. [12-core-abstractions-and-type-architecture.md](12-core-abstractions-and-type-architecture.md)
    — how the codebase abstracts its classes: Pydantic vs dataclass vs
    `Protocol`, the domain model graph, error → reason-code mapping, patterns.
13. [13-debugging-and-observability.md](13-debugging-and-observability.md) —
    how to debug: health/status surfaces, common failure signatures, dev
    tools, logging.

## Non-negotiable invariants (know these first)

- **Business output is only `OK` or `NG`.** Internal `UNCERTAIN` always maps
  to business `NG`. Never return `OK` on incomplete/invalid evidence.
- **No 100% accuracy claims** — acceptance is measured, held-out evidence
  only.
- **Edge-first**: inspection runs fully on the edge; the central server is
  never in the real-time path.
- **Original machine decisions are immutable**; human review is append-only.
- **Never delete local media** until upload + retention conditions hold.
- **Architecture boundaries** (contract 01): no YOLO inside FastAPI routes;
  no business rules inside detectors; rule engine independent of
  FastAPI/DB/YOLO; edge code never imports `training/` or central code.
- **Typed everywhere**: Pydantic models for backend contracts, generated
  TypeScript types, no `dict[str, Any]` at core boundaries; MyPy strict.
- **English only** for code, comments, docs, commits. Conventional Commits
  (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `build:`, `ci:`,
  `chore:`); branches `feat/...`, `fix/...`, `docs/...`.
- Do not commit or push unless explicitly asked.

## Repository state (2026-08-11)

- `main` contains PRs #3-#33: MVP, dashboard, M1 edge API, camera sources +
  multi-instance serve, temporal aggregation, durable upload outbox, E1-E5
  production gates, E6 acceptance-prep tooling, GigE/GenICam source,
  dashboard themes, barcode identity + PLC trigger contract (ADR-015),
  edge-local human review (ADR-016), issue templates, industrial README.
- Python uv workspace: `domain`, `vision-core`, `edge-service`, `training`
  (developer-only). TypeScript pnpm workspace: `api-client`, `ui`,
  `eslint-config`, `edge-web`, `edge-desktop`.
- The central server is **not implemented** and stays out of scope until the
  Edge gates pass and the Edge-to-central contract is frozen.
