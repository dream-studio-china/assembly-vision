# 11 — Testing and Quality Gates

How the test suites are organized, the fixture patterns each area uses, the
exact commands to run them, and what CI enforces.

## Pytest configuration (root `pyproject.toml`)

```toml
[tool.pytest.ini_options]
testpaths = ["apps/edge-service/tests", "packages/python/vision-core/tests", "training/tests", "scripts/tests"]
addopts = "-q"
markers = ["slow: slower training or integration tests"]
```

One marker exists: `slow` (currently selects exactly one test —
`training/tests/test_train.py::test_training_dry_run_on_synthetic`).

## Exact commands

```bash
uv run pytest                                  # everything
uv run pytest apps/edge-service/tests          # runtime + API + persistence + upload + retention
uv run pytest packages/python/vision-core/tests # frame sources / ROI / manifests
uv run pytest training/tests                   # av-train
uv run pytest scripts/tests                    # dataset adapters / generator / acceptance runner
uv run pytest -m "not slow"                    # fast default (what CI effectively runs)
uv run pytest -m slow                          # the Ultralytics dry-run only
uv run pytest training/tests/test_dataset.py   # single file
uv run pytest training/tests/test_artifact.py -k "manifest"  # keyword subset

make lint              # uv run ruff check .
make format            # uv run ruff format --check .
make typecheck         # uv run mypy .
make test              # uv run pytest
make web-check         # pnpm -r build && pnpm -r lint && pnpm -r test && edge-web e2e
make check             # everything
```

TypeScript:

```bash
pnpm -r build          # tsc --noEmit / vue-tsc (web build needs VITE_API_MODE=http)
pnpm -r lint
pnpm -r test           # all Vitest suites
cd apps/edge-web && pnpm test:e2e    # Playwright (needs a prior edge-web build for served-api)
pnpm --filter @assemblyvision/api-client test
pnpm --filter @assemblyvision/ui test
```

## Test inventory

| Area | Files | Fixture patterns |
|---|---|---|
| edge-service (~50 files, 759 tests) | `apps/edge-service/tests/` | `conftest.py` auto-resets the rule-identity registry; constants `REPO_ROOT/EXAMPLE_PIPELINE/EXAMPLE_RULE/PRODUCT_MANIFEST/COMPONENT_MANIFEST`; builders `make_rule`, `make_context`, `make_evidence`; tmp `output_root` + `seeded_root` (writes `inspection.json` bundles); `client = TestClient(create_app(ServerSettings(...)))`; `repo = EdgeRepository.open(tmp_path/"edge.sqlite3")`; fake detectors (`FakeProductDetector`, `RaisingComponentDetector`, ...); `token_settings` with `api_token="test-edge-token"`; in-memory PIL frames; `_AdvancingClock`/`_ScriptedSink` for scheduler tests |
| vision-core (8 files, 82 tests) | `packages/python/vision-core/tests/` | Fake frames from `Image.new`; fake OpenCV/PyAV/Harvester injected via `monkeypatch.setattr(backend, "_module", Fake)`; real loopback HTTP server fixture; real tiny `.avi` via `cv2.VideoWriter`; factory validation |
| training (6 files, 41 tests) | `training/tests/` | `yolo_dataset_dir(tmp_path)` fixture (64×64 PNGs + labels + data.yaml); `_FakeModel`/`_Boxes`/`_Tensor`/`_Result` stubs monkeypatched onto `ultralytics.YOLO`; CLI tests monkeypatch `train_detector`/`place_weights`/`write_manifest` |
| scripts (4 files, 47 tests) | `scripts/tests/` | scripts loaded via `importlib.util.spec_from_file_location`; `_make_export(tmp_path, layout=...)` builders; asserts staging dirs cleaned on failure |
| domain | none | domain is covered indirectly; keep models exercised through edge-service tests |

## Representative test idioms

Rule engine (fail-closed OK only with full evidence):

```python
def test_ok_when_all_present_and_gates_hold() -> None:
    rule = make_rule()
    context = make_context(
        components={
            "component_a": make_evidence("component_a", "PRESENT"),
            "component_b": make_evidence("component_b", "PRESENT"),
        }
    )
    decision = ENGINE.evaluate(context, rule)
    assert decision.internal_decision is InternalDecision.OK
    assert decision.business_result is BusinessResult.OK
    assert decision.reason_codes == []
```

Pipeline fail-safe (inference failure → UNCERTAIN evidence + NG, never OK):

```python
def test_component_inference_failure_is_uncertain_not_missing(tmp_path: Path) -> None:
    image_path = tmp_path / "product.png"
    _write_image(image_path)
    pipeline = _build_pipeline(
        FakeProductDetector(_Outcome(selected=_product_detection(uuid4()))),
        RaisingComponentDetector(),
    )
    record = pipeline.inspect_image(FolderSource(tmp_path), image_path, OutputWriter(tmp_path / "out"))
    assert record.decision.business_result is BusinessResult.NG
    assert "INFERENCE_ERROR" in record.decision.reason_codes
    assert all(evidence.state == "UNCERTAIN" for evidence in record.evidence)
```

API auth (token required on every route except health/live):

```python
def test_read_routes_require_token_when_configured(token_settings: ServerSettings) -> None:
    app = create_app(token_settings)
    with TestClient(app) as client:
        for path in ("/api/v1/inspections", "/api/v1/health/ready", "/api/v1/device/status"):
            denied = client.get(path)
            assert denied.status_code == 401, path
            assert denied.json()["code"] == "UNAUTHENTICATED"
            allowed = client.get(path, headers={"Authorization": "Bearer test-edge-token"})
            assert allowed.status_code in (200, 503), path
```

Persistence fencing (stale lease holder cannot mutate):

```python
# The stale worker's updates are rejected: zero rows changed.
assert repo.mark_upload_succeeded(task_id, stale_owner, now.isoformat()) == 0
assert repo.mark_upload_retry(task_id, stale_owner, "HTTP_503", later, now.isoformat()) == 0
# A current lease holder still cannot claim success without a verified receipt.
assert repo.mark_upload_succeeded(str(current.task.upload_task_id), current.lease_owner, later) == 0
```

Frontend unit (mock the service module with `vi.hoisted` + `vi.mock`):

```ts
const mocks = vi.hoisted(() => ({ getApiClient: vi.fn() }));
vi.mock("../src/services/client", () => ({ getApiClient: mocks.getApiClient }));

it("loads history on demand and allows submission only after a successful load", async () => {
  const client = {
    listInspectionReviews: vi.fn().mockResolvedValue([reviewRecord("r-1")]),
    submitReview: vi.fn().mockResolvedValue(reviewRecord("r-2")),
  };
  mocks.getApiClient.mockReturnValue(client);
  const panel = useReviewPanel("i-1", "NG", "NG");
  fillValidForm(panel);
  expect(panel.canSubmit.value).toBe(false);
  await panel.load();
  expect(panel.canSubmit.value).toBe(true);
  await panel.submit();
  expect(client.submitReview).toHaveBeenCalledWith("i-1", {
    disposition: "CONFIRMED_NG", reviewer: "operator-1", reason: null, note: null,
  });
});
```

Other frontend patterns: `vi.stubEnv("VITE_API_MODE", "http")` +
`vi.resetModules` for mode selection; `setActivePinia(createPinia())` for
stores; stubbed `fetch` injected into `new HttpApiClient("http://edge.test",
stubFetch(body))` for api-client tests.

## Writing tests for behavioral changes

- **Safety-relevant paths**: add fault-injection tests proving no `OK` on
  incomplete/invalid evidence (raise detectors/rule engine, corrupt frames,
  missing manifests, disk pressure).
- **State machines**: test every transition incl. stale-lease/fencing and
  restart recovery.
- **Contract**: update `packages/typescript/api-client/tests/contract.test.ts`
  schema assertions when API shapes change.
- **Never claim a check passed unless you ran it**; report exact commands and
  any unresolved failures.

## CI flow (`.github/workflows/ci.yml`)

- **quality** job: `uv sync` → `ruff check` → `ruff format --check` →
  `mypy` → `pytest` → **OpenAPI drift check**
  (`uv run python scripts/generate-edge-openapi.py` +
  `git diff --exit-code -- apps/edge-service/openapi/edge-openapi.json`).
- **web** job: `pnpm install --frozen-lockfile` → `pnpm -r build` with
  `VITE_API_MODE=http` → **TS contract drift check**
  (`pnpm --filter @assemblyvision/api-client generate:types` +
  `git diff --exit-code`) → `pnpm -r lint` → `pnpm -r test` → Playwright
  install → `cd apps/edge-web && pnpm test:e2e`.
- Triggered on push to `main`/`dev` and all PRs; per-ref concurrency with
  cancel-in-progress. A separate `docs.yml` builds and deploys the bilingual
  site.

## Coverage targets (contract 06 §7)

Rule Engine ≥ 95%; ROI Engine ≥ 95%; Temporal Aggregator ≥ 90%; Upload Queue
≥ 90%; API Layer ≥ 80%. Model quality is never measured by code coverage.
