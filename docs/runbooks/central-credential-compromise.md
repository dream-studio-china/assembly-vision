# Runbook C3: Central Credential Compromise

## Trigger

Suspected or confirmed exposure of a pilot administrator token, a device
upload token, a session cookie, or the MinIO access/secret key.

## Immediate Safety Action

1. **Never log, echo, or store the suspected credential** anywhere new:
   credentials are hashed with random salts in PostgreSQL, and the API never
   reads the bootstrap plaintext at runtime.
2. Suspend the affected credential immediately:
   - Device upload token: set the device row inactive
     (`devices.status != 'ACTIVE'`) so `_require_device` fails closed. M1 has
     no device disable/re-enroll API or CLI, so this is a direct,
     operator-approved database change, not an endpoint call.
   - Administrator bearer token: the pilot token is long-lived. **M1 has no
     in-place credential rotation**, and re-running `central-service bootstrap`
     does **not** re-key an existing administrator: bootstrap reuses existing
     rows and never overwrites their hashes. To revoke the token you must stop
     central access and follow the "Manual revocation" procedure below.
   - Browser session cookie: revoke sessions through
     `POST /api/v1/auth/session/revoke` (server-side revocation clears the
     HttpOnly cookie and writes an `ADMIN_SESSION_REVOKED` audit event). This
     is the only credential class with a supported revocation path in M1.
3. Confirm the API is not exposing the credential: `/api/v1/health/*` and
   problem responses never include tokens, object keys, or internal paths.

### Manual revocation (M1, no in-place rotation)

Until automated credential rotation ships, revoking a compromised pilot
administrator or device token is a documented database-level incident action:

1. Stop the API and bootstrap services so no further action uses the stolen
   credential.
2. Using the migration/owner database role, rotate the stored hash directly
   (replace `upload_token_hash`/`upload_token_salt` on the device row or
   `token_hash`/`token_salt` on the administrator row) and record an
   `audit_logs` row naming actor, action, target, request/incident id, and
   reason.
3. Restart the services; the old credential now fails closed.
4. Provision the new credential out of band and keep it in the deployment
   secret store, never in logs or the repository.

This procedure must itself be pre-approved and is out of scope for the
automated bootstrap path.

## Diagnosis

1. Query `audit_logs` for the affected window using `actor_type`,
   `actor_id`, `request_id`, and `action` to reconstruct what the credential
   did:

   ```sql
   SELECT created_at, actor_type, action, target_type, target_id, request_id
   FROM audit_logs WHERE created_at >= now() - interval '24 hours'
   ORDER BY created_at;
   ```

2. Confirm which devices/uploads were accepted under the affected identity and
   whether any replay/conflict anomalies exist in `upload_receipts`.
3. For MinIO key exposure: rotate `AV_CENTRAL_MINIO_ACCESS_KEY` /
   `AV_CENTRAL_MINIO_SECRET_KEY` and update the bucket policy; object keys are
   opaque and tenant-scoped, so a key leak does not expose the database.

## Recovery

1. Rotate MinIO keys first (change `AV_CENTRAL_MINIO_ACCESS_KEY` /
   `AV_CENTRAL_MINIO_SECRET_KEY`, restart MinIO, update the bucket policy).
   Object keys are opaque and tenant-scoped, so a key leak does not expose the
   database, but the root credential still controls every object.
2. Revoke browser sessions via `POST /api/v1/auth/session/revoke` (supported
   in M1).
3. Device and administrator tokens have **no automated rotation in M1**; use
   the "Manual revocation" procedure above for each affected principal.
4. Re-verify the edge scheduler authenticates with the new device tokens and
   that accepted inspections replay duplicate-free (device identity is
   unchanged; only the credential rotated).
5. Audit every action performed during the suspected window and preserve
   evidence; add the request IDs to the incident record.

## Verification

- The old device credential returns `401 UNAUTHENTICATED` and the new one
  authenticates (after the manual rotation procedure).
- Old admin bearer fails `GET /api/v1/auth/me`; a fresh session works and the
  `ADMIN_SESSION_REVOKED` audit row exists.
- Readiness still reports `credentials: ok`.

## Escalation

- Any sign the compromise touched MinIO objects or cross-organization data:
  engage security/storage owners and review object keys and audit rows before
  resuming the pilot.
- Compromise of a production (non-pilot) credential store is out of M1 scope
  and must follow the organization's security incident process.
