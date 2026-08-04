# 08. Security, Permissions, and Audit

## 1. Recommended Roles

- Administrator
- Engineer
- Operator
- Reviewer
- Viewer

## 2. Backend Authorization

Hiding UI buttons is not an authorization boundary.

Permissions must be enforced by the FastAPI backend.

## 3. Privileged Operations

The following operations require elevated permissions:

- Model activation
- Rule publication
- Threshold changes
- Data deletion
- Remote device configuration
- User management
- Human-review actions that change business status

## 4. Release Lifecycle

Models and rules should follow:

```text
Draft
→ Validated
→ Approved
→ Active
→ Retired
```

Production rules must not be edited in place without versioning.

## 5. Audit Logging

Audit the following:

- Product-configuration changes
- Rule changes
- Threshold changes
- Model activation
- Human review
- Record deletion
- Permission changes
- Device-configuration changes
- Remote operations

Audit entries should contain at least:

- Actor
- Action
- Target
- Before state
- After state
- Timestamp
- Device or site
- Trace ID

## 6. Source Distribution

The goal of client-side packaging is to prevent casual source browsing, not advanced reverse engineering.

Allowed measures include:

- `.pyc` distribution
- Docker images
- Multi-stage builds
- Removing original `.py` files from production images
- Deploying only built frontend assets

The documentation must clearly state:

- `.pyc` is not strong anti-reverse-engineering protection.
- Docker is not a source-code security boundary.
- Long-term secrets must not be embedded in images.

## Related Documents

- [REST API and Events - authorization](../design/15-rest-api-and-events.md)
- [Security and Source Distribution](../design/21-security-and-source-distribution.md)
- [Central Admin Dashboard](../design/17-central-admin-dashboard.md)
- [Appendices - audit and reason codes](../design/appendices.md)
