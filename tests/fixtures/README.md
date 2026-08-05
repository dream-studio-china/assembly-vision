# Test Fixtures

Small synthetic, non-sensitive images and payloads used by fast CI tests.

Tests must not import fixtures from production data directories. Real
production images and labeled datasets live outside the Git repository and are
invoked separately from CI (docs/design/18-monorepo-and-code-organization.md).
