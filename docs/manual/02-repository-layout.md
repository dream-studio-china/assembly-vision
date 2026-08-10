# 02 — Repository Layout

Two workspaces in one monorepo: a Python uv workspace (runtime + shared
packages + training) and a TypeScript pnpm workspace (dashboard, desktop,
shared frontend packages).

## Top-level

| Path | Contents |
|---|---|
| `pyproject.toml` | Root uv workspace: members `apps/edge-service`, `packages/python/domain`, `packages/python/vision-core`, `training`; Ruff/MyPy/Pytest config |
| `package.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml` | pnpm workspace: `apps/*`, `packages/typescript/*` |
| `Makefile` | `sync`, `lint`, `format`, `typecheck`, `test`, `web-install`, `web-check`, `check` |
| `.github/workflows/ci.yml` | `quality` job (Python gates + OpenAPI drift) + `web` job (pnpm build/lint/test + TS contract drift + Playwright e2e) |
| `.github/workflows/docs.yml` | Bilingual MkDocs build + GitHub Pages deploy |
| `config/examples/` | `pipeline.yaml`, `pipeline.cameras.yaml`, `product-rule.yaml` |
| `models/manifests/` | Placeholder product/component manifests (weights live outside Git) |
| `tests/fixtures/` | Small synthetic non-sensitive fixtures for fast CI |
| `docs/` | Design, decisions (ADRs), contracts, runbooks, research, reviews, tasks, this manual |

## Python workspace

### `apps/edge-service` — package `assemblyvision_edge` (console script `assemblyvision`)

The inspection runtime + local API. Everything under
`apps/edge-service/src/assemblyvision_edge/`:

| Module | Purpose |
|---|---|
| `cli.py` | `inspect`, `verify`, `serve`, `backup`, `restore` subcommands |
| `config.py` | Pipeline/rule/edge config loading + all validation gates; durable rule-identity registry |
| `pipeline.py` | `InspectionPipeline`: image→record flow, provenance checks, fail-closed decision merge |
| `camera_manager.py` | `CameraSourceManager`: one capture thread per instance, bounded queue, overflow tracking |
| `verify.py` | Held-out verification scoring + report formatting |
| `backup.py` | `backup_edge` / `restore_edge` (checksummed tar.gz bundles) |
| `healthcheck.py` | `python -m assemblyvision_edge.healthcheck <url>` container liveness |
| `barcode/` | `models`, `protocols` (`BarcodeDecoder`), `zxing` (ZXing-cpp), `keyboard` (dev sim), `resolver` (exact-mapping) |
| `detection/` | `product_detector` (stage 1), `component_detector` (stage 2), `raw` (Ultralytics box extraction), `registry` (`ModelRegistry` shared weights) |
| `api/` | `app` (`create_app`), `settings` (Server/Upload/Storage/Retention/IntegrityScan), `state` (`EdgeRuntime`/`InstanceRuntime`), `deps` (auth), `events` (`RuntimeEventBus`), `problems` (RFC 7807), `logging_buffer`, `schemas` |
| `api/routers/` | `auth`, `camera`, `configuration`, `derived`, `dev`, `device`, `health`, `inspection`, `inspections`, `logs`, `media`, `reviews`, `uploads`, `ws` |
| `output/` | `writer.py`: atomic bundle publish (`inspection.json` + media), annotation rendering |
| `persistence/` | `schema` (SQLAlchemy Core tables), `repository` (`EdgeRepository`), `migrate` (Alembic), `reconcile` (import/scan/quarantine) |
| `retention/` | `policy`, `storage` (pressure modes), `worker` (`RetentionCleanupWorker`, `O_NOFOLLOW` unlink) |
| `rules/` | `rule_engine.py` (`RuleEngine.evaluate`, `rule_version_id`) |
| `temporal/` | `aggregator` (`TemporalAggregator`), `window_manager` (`ProductWindowManager`) |
| `trigger/` | `source` (`TriggerSource`, `MockTriggerSource`, `IdentityCorrelator`), `modbus_tcp` (opt-in contract) |
| `upload/` | `scheduler` (`UploadScheduler`, Http/Directory sinks, token bucket, circuit breaker) |

Also: `migrations/` (Alembic), `openapi/edge-openapi.json` (committed,
drift-checked), `Dockerfile`, `compose.yaml`, `pyproject.toml`,
`tests/` (~50 test files).

### `packages/python/domain` — package `assemblyvision_domain`

Canonical Pydantic models, errors, reason codes. Only dependency: pydantic.

- `models.py` — `APIModel` base (`extra="forbid"`, `from_attributes=True`);
  enums `InternalDecision`, `BusinessResult`, `InspectionLifecycle`,
  `MediaLifecycle`, `ReviewDisposition`, `ComponentCorrectionState`; models
  `BoundingBox`, `Detection`, `FrameQuality`, `FrameQualitySummary`,
  `BarcodeResult`, `ProductResolution`, `MediaMetadata`, `ProductDetection`,
  `ROIResult`, `ComponentDetection`, `AggregatedComponentEvidence`,
  `InspectionDecision`, `InferenceSettings/StageMetadata/Metadata`,
  `InspectionRecord`, `UploadTask`, `Artifact`, `DatasetReference`,
  `ModelMetric`, `ModelManifest`, `ComponentCorrection`, `ReviewRecord`;
  helper `allowed_review_dispositions(...)`.
- `errors.py` — `AssemblyVisionError` base; `ConfigError`, `ImageReadError`,
  `DetectionError` (carries `.reason_code`), `ROIGenerationError`,
  `RuleEvaluationError`, `OutputError`.
- `reason_codes.py` — the enforceable canonical reason-code set.

### `packages/python/vision-core` — package `assemblyvision_vision`

ROI engine, frame sources, manifest loading. Optional extras `video`, `rtsp`,
`http`, `gige` keep it lean for central/lightweight consumers.

- `roi/roi_engine.py` — `ROIConfig`, `ROIEngine.generate` (expand→clip→reject→crop).
- `roi/geometry.py` — pure `Box`/`Transform` helpers (`expand`, `clip`,
  `retained_fraction`, `translation_transform`, `inverse_transform`,
  `apply_transform`).
- `sources/` — `FrameSource` protocol + `CapturedFrame`; `FolderSource`,
  `VideoFrameSource`, `OpenCVCameraSource`, `RTSPFrameSource`,
  `HttpImageSource`, `GigEVisionFrameSource`; lazy backends (`_opencv`,
  `_av`, `_harvester`, `_pacing`); `factory.py` (`build_frame_source`,
  `FrameSourceConfig`).
- `manifests.py` — `load_model_manifest`, `verify_manifest_artifact`
  (relative URI + size + SHA-256), `verify_model_class_map`,
  `model_version_label`, `sha256_file`.

### `training` — package `assemblyvision-training` (console script `av-train`)

Developer-only; **never imported by the runtime**. Subcommands `product`,
`prepare-components`, `component`. Modules: `cli.py`, `dataset.py`
(validation), `prepare_components.py` (ROI dataset generation),
`train.py` (Ultralytics wrapper), `artifact.py` (immutable weights/manifests/
run metadata). Base weights cached in `training/.cache/weights/`.

## TypeScript workspace

| Package | Purpose |
|---|---|
| `packages/typescript/api-client` (`@assemblyvision/api-client`) | `ApiClient` interface, `MockApiClient`, `HttpApiClient`, `validate.ts`, `websocket.ts`, `types.ts`, generated `src/edge/generated/api.ts` |
| `packages/typescript/ui` (`@assemblyvision/ui`) | `DetectionViewer`, `StatusBadge`, `status.ts`, `geometry.ts`, `formatters/format.ts` |
| `packages/typescript/eslint-config` | Shared flat ESLint config |
| `apps/edge-web` | Vue 3 + Vite dashboard; `src/{pages,components,composables,stores,services,router}`; `tests/` (Vitest) + `tests/e2e/` (Playwright) |
| `apps/edge-desktop` | Electron shell (context isolation, sandbox, kiosk); loads built edge-web output |

## Scripts (`scripts/`)

| Script | Purpose |
|---|---|
| `generate-synthetic-dataset.py` | Procedural two-stage labeled dataset (fixed seed 2026) |
| `adapt-roboflow-dataset.py` / `adapt-xanylabeling.py` | Real export → two-stage layout, strict validation, atomic publish |
| `e2e-demo.sh` | Full train→prepare→train→inspect→verify smoke with hard FN gate |
| `generate-edge-openapi.py` | Regenerate committed edge OpenAPI (CI drift check) |
| `translate-docs.py`, `generate-mkdocs-configs.py`, `build-docs.sh` | Bilingual docs build |
| `edge-acceptance-run.py` | E6 local acceptance runner (exit 0/1/2) |
| `tests/` | Pytest for adapters/generator/acceptance runner |
