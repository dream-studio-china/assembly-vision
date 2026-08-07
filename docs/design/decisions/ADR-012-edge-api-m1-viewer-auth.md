# ADR-012: Edge API M1 Viewer Authentication and Read-Only Boundary

## 1. Status

Accepted

## 2. Context

The read-only M1 edge API (`assemblyvision serve`, `/api/v1`) serves inspection
history, media, configuration, and logs to the locally served dashboard.
Design 15.2.1 requires that mutating routes need `operator` or `edge_admin`
roles and explicitly states that localhost binding is not authentication.
Contract 08 requires backend enforcement and forbids treating hidden UI buttons
as an authorization boundary.

A full offline edge-session implementation (credential issuance, validation,
expiry, refresh, role model, CSRF protection) is a production milestone and is
not required for the M1 read-only integration demonstrator. However, shipping an
unauthenticated API with a wildcard CORS policy violates the accepted contracts
and lets any reachable client read inspection data and any website issue
cross-origin requests.

## 3. Decision

For the M1 read-only edge API:

1. **No mutating routes are exposed.** Pause/resume, camera reconnect, and
   upload retry endpoints are removed and return `404`. UI controls for these
   commands are removed or disabled. An inspection coordinator and operator
   commands are a later milestone and will require the documented operator/admin
   role model before activation.
2. **Viewer authentication uses a shared-secret bearer token** configured via
   `AV_EDGE_API_TOKEN` (or the `serve --api-token` argument). When configured,
   every route except the deliberately minimal `GET /api/v1/health/live`
   requires `Authorization: Bearer <token>` and returns `401 UNAUTHENTICATED`
   otherwise. When no token is configured the service runs in an explicit M1
   development mode; this must never be presented as production authentication.
3. **CORS never uses `*`.** Cross-origin requests are allowed only for anchored
   loopback development origins (`localhost` / `127.0.0.1` on any port) so the
   Vite dev server works; the served dashboard is same-origin and needs no CORS.
   Loopback binding, CORS, and origin allowlists are not authentication.
4. **The session mechanism is documented here**; a full role-based edge session
   (viewer/operator/edge-admin, expiry, CSRF protection, audit attribution) is
   the production requirement recorded in the roadmap.

## 4. Consequences

### 4.1 Positive

- The read-only M1 API satisfies contract 08 backend enforcement and design
  15.2.1's "do not treat localhost as authentication" requirement within its
  scope.
- Removing M1 mutation endpoints eliminates unauthenticated control surface and
  the false `paused_by = "operator"` attribution.
- Wildcard CORS is gone, so a browser on the management network cannot read
  inspection data cross-origin.
- The token mechanism is small, deterministic, and directly testable.

### 4.2 Negative and Trade-offs

- Without a configured token the M1 API remains open to network clients that can
  reach the service; this is a documented development-mode boundary, not
  production authentication.
- A shared token is coarse: it provides viewer access but no per-actor
  attribution, no expiry, and no operator/admin separation. This is
  intentionally deferred to the production edge-session milestone.
- Embedding a token in the served bundle is not required (same-origin serving
  uses no CORS and browsers enforce the same-origin policy), so no secret needs
  to ship in frontend assets.

## 5. Open Questions and Validation Required

- Select the offline edge-session mechanism (local operator login vs. provisioned
  device credential), expiry, and emergency-pause authorization for production.
- Confirm whether inspection history beyond the current M1 scope requires the
  central viewer role model at the edge.

## 6. Links

- [ADR-006: REST Plus WebSocket](ADR-006-rest-plus-websocket.md)
- [REST API and Events](../15-rest-api-and-events.md)
- [Edge Dashboard](../16-edge-dashboard.md)
- [Security, Permissions, and Audit](../../contracts/08-security-permissions-and-audit.md)
