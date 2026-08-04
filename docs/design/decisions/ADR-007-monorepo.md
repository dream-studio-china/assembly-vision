# ADR-007: Monorepo

## 1. Status

Accepted

## 2. Context

AssemblyVision includes edge and central Python services, two Vue applications, reusable vision/domain packages, generated API clients, training/evaluation code, deployment definitions, and cross-system tests. These parts evolve through shared schemas and coordinated releases, especially during a small-team MVP.

## 3. Decision

Keep application, package, training, deployment, test, configuration, and documentation source in one repository. Runnable units live under `apps/`; reusable Python and TypeScript code under `packages/python/` and `packages/typescript/`; training/evaluation under `training/`; development model metadata under `models/`; deployment under `deploy/`; cross-application tests under `tests/`; architecture under `docs/`.

Runtime production data, customer evidence, secrets, deployed databases, and production model weights are not stored in Git. Packages are created only for real reuse or boundary value; the MVP does not mirror every conceptual component with a separate package.

## 4. Scope

The decision governs source organization and CI change coordination. It does not require all applications to be deployed together, share one runtime image, or release at the same version.

## 5. Consequences

### 5.1 Positive

- Atomic changes across schemas, generated clients, services, UI, tests, and documentation.
- Easier code reuse and consistent quality tooling for a small team.
- Cross-application integration tests run against one revision.
- Architecture decisions and deployment definitions remain close to implementation.

### 5.2 Negative and Trade-offs

- CI must detect affected projects and avoid unnecessary full rebuilds.
- Ownership and dependency boundaries need enforcement.
- Repository access grants visibility across multiple applications.
- Large model/data artifacts require external storage and manifest discipline.

## 6. Alternatives

- **Repository per service/application:** rejected initially because coordinated contracts and small-team changes would incur version/review overhead.
- **Backend and frontend repositories:** viable later but weakens atomic OpenAPI/client updates.
- **Store models and datasets in Git/LFS:** rejected for production data, scale, privacy, and release-governance reasons; manifests reference controlled artifact stores.

## 7. Open Questions and Validation Required

- Package/build tools and affected-project CI strategy.
- Code ownership and release versioning by application/model/rule.
- Controlled artifact registry for models, datasets, and generated packages.

## 8. Links

- [Roadmap](../25-roadmap.md)
- [Testing and Quality Assurance](../22-testing-and-quality-assurance.md)
- [ADR-002: Python backend](ADR-002-python-backend.md)
- [ADR-003: Vue 3 and TypeScript frontend](ADR-003-vue-3-and-typescript-frontend.md)
