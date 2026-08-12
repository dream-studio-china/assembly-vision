# Runbook C3: Central Credential Compromise

## Trigger

Suspected or confirmed exposure of a pilot administrator token, a device
upload token, a session cookie, or the MinIO access/secret key.

## Immediate Safety Action

1. **Never log, echo, or store the suspected credential** anywhere new:
   credentials are hashed with random salts in PostgreSQL, and the API never
   reads the bootstrap plaintext at runtime.
2. Suspend the affected credential immediately:
   - Device upload token: disable the device row
     (`devices.status != 'ACTIVE'`) so `_require_device` fails closed;
     re-enrollment issues a fresh token.
   - Administrator bearer token: the pilot token is long-lived; rotate the
     `AV_CENTRAL_ADMIN_TOKEN` bootstrap value, re-run bootstrap to re-hash,
     and revoke open admin sessions.
   - Browser session cookie: revoke sessions through
     `POST /api/v1/auth/session/revoke` (server-side revocation clears the
     HttpOnly cookie and writes an `ADMIN_SESSION_REVOKED` audit event).
3. Confirm the API is not exposing the credential: `/api/v1/health/*` and
   problem responses never include tokens, object keys, or internal paths.

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

1. Rotate credentials in order: MinIO keys, device upload tokens (re-enroll
   each affected device with a new secret-file value), then the administrator
   bootstrap token and session revocation.
2. Re-verify the edge scheduler authenticates with the new device tokens and
   that accepted inspections replay duplicate-free after re-enrollment
   (device identity is unchanged; only the credential rotated).
3. Audit every action performed during the suspected window and preserve
   evidence; add the request IDs to the incident record.

## Verification

- The old device credential returns `401 UNAUTHENTICATED` and the new one
  authenticates.
- Old admin bearer fails `GET /api/v1/auth/me`; a fresh session works and the
  `ADMIN_SESSION_REVOKED` audit row exists.
- Readiness still reports `credentials: ok` after re-bootstrap.

## Escalation

- Any sign the compromise touched MinIO objects or cross-organization data:
  engage security/storage owners and review object keys and audit rows before
  resuming the pilot.
- Compromise of a production (non-pilot) credential store is out of M1 scope
  and must follow the organization's security incident process.
