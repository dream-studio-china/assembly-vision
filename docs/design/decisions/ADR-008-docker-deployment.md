# ADR-008: Docker Deployment

## 1. Status

Accepted

## 2. Context

The edge and central runtime include Python/native dependencies, model runtimes, Web assets, databases, and proxies. Reproducible installation and rollback are needed across customer-controlled hardware. The edge should remain operable by a small team and must not depend on Kubernetes.

## 3. Decision

Package applications as multi-stage Docker images and deploy initial edge and central profiles with Docker Compose. Run non-root, use environment/runtime-file configuration, explicit persistent volumes, health checks, restart policies, pinned images, and read-only root filesystems where practical. Nginx serves static assets and acts as a reverse proxy where appropriate.

The edge deployment does not use Kubernetes. Central Kubernetes support is a future option only when scale and operations justify it. Camera access receives only validated device/socket permissions; `privileged: true` is not the default.

## 4. Scope

This applies to the one-month and production runtime packaging. The static train-and-inspect MVP may run directly in a developer environment. Host drivers, GPU runtime, camera SDK, volume backups, and OS hardening remain installation responsibilities outside container images.

## 5. Consequences

### 5.1 Positive

- Reproducible dependency and application packaging.
- Explicit service, network, health, and persistence configuration.
- Straightforward versioned rollout and rollback.
- Common deployment approach across edge and initial central environments.

### 5.2 Negative and Trade-offs

- Camera/GPU/vendor SDK integration can require host-specific setup.
- Compose is not a complete fleet orchestrator or high-availability platform.
- Persistent state, backup, logs, and secrets need controls beyond image build.
- Docker does not protect source from a host administrator.

## 6. Alternatives

- **Host-native installation:** rejected as the primary method due to dependency drift and harder rollback; may be needed for a vendor adapter only.
- **Kubernetes at the edge:** rejected as disproportionate operational complexity.
- **Virtual machine appliance:** viable customer packaging option but does not replace application containers and host hardware integration.
- **Single all-in-one container:** rejected because application, proxy, and stateful service lifecycles should remain separable.

## 7. Open Questions and Validation Required

- Edge OS, GPU/container runtime, camera SDK licensing, and device-access compatibility.
- Customer registry/offline image-transfer and patching process.
- Central availability topology and whether future Kubernetes is justified.

## 8. Links

- [Deployment and Operations](../20-deployment-and-operations.md)
- [Security and Source Distribution](../21-security-and-source-distribution.md)
- [ADR-001: Edge-first inspection](ADR-001-edge-first-inspection.md)
