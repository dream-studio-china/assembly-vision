# 06 — Adding a REST Endpoint (End-to-End Recipe)

This is the canonical recipe for adding a new edge API endpoint, based on the
existing `reviews` and `uploads` routers. Follow every step; the CI drift
checks will fail if the contract pieces are out of sync.

## Step 1 — Domain model (if a new shape is needed)

Add/reuse a Pydantic model in `packages/python/domain/src/
assemblyvision_domain/models.py` (base `APIModel`, `extra="forbid"`).
Value/request models that are only API-specific go in
`apps/edge-service/src/assemblyvision_edge/api/schemas.py`.

## Step 2 — Repository method (if persistence is needed)

Add the query/mutation to `EdgeRepository` in
`persistence/repository.py`. Follow the existing patterns:
- Read queries return typed rows/summaries; use `WHERE ... AND` for filters
  and keyset pagination `(sort_key, id) < (:cursor, :id)`.
- Mutations use short `begin()`/immediate transactions with
  compare-and-set state transitions (e.g. `UPDATE upload_tasks SET status=?
  WHERE upload_task_id=? AND status IN ('RETRY_WAIT','PERMANENT_FAILURE')`),
  and write tests proving the transitions.

## Step 3 — Router

Create `api/routers/your_resource.py` modeled on `reviews.py`/`uploads.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query

from assemblyvision_edge.api.deps import require_viewer
from assemblyvision_edge.api.schemas import Problem  # noqa: F401 (typed errors)
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(prefix="/api/v1/your-resource", tags=["your-resource"])


@router.get("", response_model=..., responses={404: {"model": Problem}})
def list_your_resource(
    limit: int = Query(50, ge=1, le=200),
    repo: EdgeRepository = Depends(get_repository),  # see Step 4
    viewer=Depends(require_viewer),
) -> ...:
    ...
```

- Use `Depends(require_viewer)` for viewer-authenticated routes (everything
  except `/health/live`). There is no separate operator/admin dependency on
  the edge yet (ADR-012/016); admin-only *pages* are enforced in the
  frontend.
- Errors: raise `ApiProblem(status_code, code, detail)` from `problems.py`
  (renders `application/problem+json`), or use `HTTPException` only for
  FastAPI-native 422s. Never return raw stack traces or paths.

## Step 4 — Wire the dependency and register the router

- In `api/deps.py`: if you need a new accessor, add a
  `get_your_resource` dependency mirroring `get_repository`/`get_runtime`
  (they read `request.app.state.*`).
- In `api/app.py`: `from assemblyvision_edge.api.routers import your_resource`
  and `app.include_router(your_resource.router)`. Set the router up so its
  routes are added before the SPA fallback (the `/api/*` 404 guard is
  registered after routers).

## Step 5 — OpenAPI + TypeScript regeneration

```bash
uv run python scripts/generate-edge-openapi.py            # rewrites apps/edge-service/openapi/edge-openapi.json
pnpm --filter @assemblyvision/api-client generate:types   # rewrites packages/typescript/api-client/src/edge/generated/api.ts
```

CI runs both and fails on `git diff` drift, so commit the regenerated files.

## Step 6 — API client (frontend contract)

In `packages/typescript/api-client/src/edge/`:

1. `ApiClient.ts` — add the method signature with a JSDoc citing the design
   doc (the interface is the only thing the dashboard imports).
2. `HttpApiClient.ts` — implement using the private `#request(path, init?,
   validator?)` helper: it prefixes `/api/v1`, attaches the bearer token,
   uses `credentials: "same-origin"`, parses non-2xx `Problem` bodies into
   `ApiError`, and runs a runtime validator.
3. `validate.ts` — add a `validate*` function checking every field the UI
   reads (helpers: `expectRecord`, `hasString`, `hasNumber`, `hasBoolean`,
   `hasOneOf`, `hasArray`, `hasRecord`, `pageOf`) and register it in the
   `validators` record. This is the F9 runtime guard — drifted payloads
   become `ApiError(0, "INVALID_RESPONSE", ...)` instead of silent casts.
4. `types.ts` — add hand types if new payload shapes are exposed (copy the
   `ReviewRecord`/`SubmitReviewRequest` block; keep in sync with the Pydantic
   models).
5. `MockApiClient.ts` — implement the method with **deterministic** data and
   **mirror the server's validation and error codes** (e.g. `404
   NOT_FOUND`, `409 TASK_NOT_RETRYABLE`, `422 REVIEW_DISPOSITION_INVALID`).
   This keeps UI error handling identical in mock and http mode.

## Step 7 — Frontend consumption (optional)

Follow the layered pattern (details in `10-frontend-development.md`):
View → Composable/Store → Service → `getApiClient()`. Add the route entry in
`apps/edge-web/src/router/index.ts` (meta `requiresAuth`, `admin` for admin
pages) and a nav link in `App.vue` if needed.

## Step 8 — Tests

- **Python**: add `apps/edge-service/tests/test_your_api.py` using
  `TestClient(create_app(ServerSettings(...)))` with a tmp output root;
  authenticate with `headers={"Authorization": "Bearer test-edge-token"}`;
  assert both success bodies and problem responses (status + `code`).
  Persistence behavior tests go with the repository tests.
- **TypeScript**: extend `packages/typescript/api-client/tests/` (mock
  parity + `HttpApiClient` URL/error mapping with a stubbed `fetch`) and
  `apps/edge-web/tests/` for any store/composable logic.
- **E2E** (optional): extend `apps/edge-web/tests/e2e/served-api.spec.ts`,
  which spawns the real service and drives the browser.

## Checklist

- [ ] Pydantic model in `domain` or `schemas.py` (`extra="forbid"`)
- [ ] Repository method with CAS transitions + tests
- [ ] Router with `require_viewer` + typed responses + `ApiProblem` errors
- [ ] Router registered in `app.py`
- [ ] OpenAPI regenerated + committed (drift check)
- [ ] TS types regenerated + committed (drift check)
- [ ] `ApiClient` interface + Http + Mock + validators + hand types
- [ ] Frontend route/view/service wired (if UI-facing)
- [ ] Python + TS tests; `ruff`/`mypy`/`pytest`/`pnpm` gates pass
