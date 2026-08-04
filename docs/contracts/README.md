# AssemblyVision Engineering Contracts

This directory defines the mandatory engineering contracts for AssemblyVision.

These documents are intended to serve as:

- Architecture constraints
- Coding and interface rules
- CI quality gates
- Runtime validation rules
- Model and rule release criteria
- Industrial-site change-control rules
- Customer acceptance criteria

The contracts should be treated as enforceable engineering rules, not as optional guidance.

## Contract Index

1. [01 - Architecture Boundaries](01-architecture-boundaries.md)
2. [02 - Code and Interface Contracts](02-code-and-interface-contracts.md)
3. [03 - AI, Rule Engine, and Fail-Safe Contracts](03-ai-rule-and-safety-contracts.md)
4. [04 - Edge, Storage, and Upload Contracts](04-edge-storage-upload-contracts.md)
5. [05 - Data, API, and Versioning Contracts](05-data-api-and-versioning-contracts.md)
6. [06 - Testing, Quality, and CI Contracts](06-testing-quality-and-ci-contracts.md)
7. [07 - Deployment, Observability, and Operations](07-deployment-observability-and-operations.md)
8. [08 - Security, Permissions, and Audit](08-security-permissions-and-audit.md)
9. [09 - Industrial Site and Change Control](09-industrial-site-and-change-control.md)
10. [10 - Model, Rule, Release, and Acceptance](10-model-rule-release-and-acceptance.md)
11. [11 - Minimum Mandatory Contracts](11-minimum-mandatory-contracts.md)
12. [Contributor rules](../contributing.md)

## Related Documentation

- [Design documentation index](../design/README.md) — the architecture baseline these contracts constrain
- [Decision consistency checklist](../design/appendices.md#2-decision-consistency-checklist) — design-level invariants
- [Reason-code glossary](../design/appendices.md#4-reason-code-glossary) — stable decision codes
- [Open questions](../design/appendices.md#3-global-open-questions) — unresolved items affecting contracts
- [Architecture decisions](../design/decisions/README.md) — accepted ADRs referenced by the contracts
- [Source brief](../source-brief.md) — historical input; ADRs, contracts, and current design are normative

## Enforcement Principle

Whenever possible, a contract violation should become an automated failure condition.

Examples:

- CI fails when module dependency boundaries are violated.
- MyPy fails when core interfaces are insufficiently typed.
- Services do not enter the Ready state when model or rule versions are missing.
- Local cleanup jobs do not delete media that has not been uploaded.
- The inspection pipeline never returns `OK` when evidence is incomplete or invalid.
