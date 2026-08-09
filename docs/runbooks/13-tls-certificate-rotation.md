# Runbook 13: TLS Certificate Rotation

## Trigger

Certificate near expiry, suspected compromise, or a required renewal per the
customer certificate policy.

## Immediate Safety Action

1. Do not remove the current certificate until the replacement validates.
2. Record site/device, start/end time, actor, affected services, actions,
   result, and escalation reference.
3. Confirm the certificate and private key are not world-readable; the edge
   service rejects a private key readable by group or others.

## Rotation Procedure (edge-service local TLS)

1. Obtain the replacement certificate and key from the approved CA and place
   them where the runtime can read them (for example a Docker secret mounted at
   `/run/secrets/edge_tls_cert` and `/run/secrets/edge_tls_key` with mode
   `0400`).
2. Validate the pair before activating it:

   ```text
   openssl x509 -in cert.pem -noout -dates
   openssl verify -CAfile <ca-bundle> cert.pem
   ```

3. Update the certificate/key mount or `AV_EDGE_TLS_CERT` / `AV_EDGE_TLS_KEY`
   paths, then restart the edge service.
4. Confirm the service starts (the certificate/key pair is validated at
   startup, including match and permissions), then verify:

   ```text
   curl --cacert <ca-bundle> https://127.0.0.1:8000/api/v1/health/live
   ```

   and confirm the presented certificate is the new one.
5. Confirm WebSocket connections still authenticate (`/api/v1/ws/runtime`)
   from the dashboard and that uploads still reach the central endpoint.

## Rotation Procedure (upstream factory proxy)

1. Follow the customer proxy certificate rotation procedure; the edge service
   configuration does not change.
2. Confirm the proxy forwards `X-Forwarded-Proto` and that the dashboard and
   WebSocket URLs use `https:`/`wss:` as documented.

## Exit Criteria

Health/live returns over TLS with the new certificate, WebSocket and REST
authentication work, uploads succeed, and the old certificate no longer
validates.

## Related

- [Repeated Container Restart](06-repeated-container-restart.md)
