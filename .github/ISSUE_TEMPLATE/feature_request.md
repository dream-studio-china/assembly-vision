---
name: Feature request
description: Propose a new capability or behavior change for AssemblyVision
title: "[feat]: "
labels: ["enhancement"]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for proposing an improvement. Review the [architecture overview](https://github.com/dream-studio-china/assembly-vision/tree/main/docs/design/03-architecture-overview.md) and the relevant ADRs first, and link them below so reviewers can trace your proposal.
  - type: dropdown
    attributes:
      label: Scope
      description: Which milestone or area does this belong to?
      options:
        - Edge runtime (inspect/verify/serve, pipeline, rules, detectors)
        - Edge dashboard / desktop (frontend)
        - Backend API / persistence / upload / retention
        - Human review and review tooling
        - Camera / barcode / trigger hardware integration (GigE, ZXing, Modbus FIFO)
        - Training and dataset tooling
        - Documentation
        - Infrastructure / CI / packaging
    validations:
      required: true
  - type: dropdown
    attributes:
      label: Architecture decision
      description: Does this change public architecture or behavior, requiring an accepted ADR before implementation?
      options:
        - "No: additive change within existing decisions"
        - "Yes: requires an accepted ADR (recorded in docs/design/decisions/)"
    validations:
      required: true
  - type: textarea
    attributes:
      label: Problem statement
      description: What problem does this solve, and for whom? Include acceptance thresholds or constraints if known.
    validations:
      required: true
  - type: textarea
    attributes:
      label: Proposed approach
      description: Describe the suggested implementation and how it preserves the edge-first architecture and the separation of AI inference, rule evaluation, persistence, and Web APIs.
    validations:
      required: true
  - type: textarea
    attributes:
      label: Acceptance criteria
      description: Concrete, testable outcomes. Fail-safe and NG/UNCERTAIN behavior must be explicit where decisions are involved; state the impact on the E1-E6 gates or E6 on-site acceptance where applicable.
    validations:
      required: true
  - type: textarea
    attributes:
      label: Architecture alignment
      description: Link the relevant design documents, ADRs, and engineering contracts. Note any conflict with existing decisions.
      placeholder: "docs/design/13-upload-and-synchronization.md, ADR-005, docs/contracts/04-edge-storage-upload-contracts.md"
  - type: textarea
    attributes:
      label: Test plan
      description: Which tests will cover this (unit, API contract, Playwright e2e, model evaluation, resilience)? Report the exact commands to run.
  - type: checkboxes
    attributes:
      label: Documentation impact
      description: Documentation is part of the implementation (AGENTS.md §7). Select what must be updated with this change.
      options:
        - label: "Design document (docs/design/)"
        - label: "ADR (docs/design/decisions/)"
        - label: "Engineering contract (docs/contracts/)"
        - label: "Runbook (docs/runbooks/)"
        - label: "README / QUICKSTART"
  - type: checkboxes
    attributes:
      label: Change-control impact
      description: Does this touch a versioned or release-governed surface (contracts 05/09/10)?
      options:
        - label: "Public API (contract 05 - versioned paths, OpenAPI/TS contract)"
        - label: "Database schema (Alembic migration, contract 05)"
        - label: "Configuration format (pipeline / rule / model manifest)"
        - label: "Model or rule release lifecycle (contract 10)"
        - label: "Deployment / operational behavior (contract 07)"
  - type: dropdown
    attributes:
      label: Dependency
      description: Does this require hardware, customer data, or an external decision?
      options:
        - "No: can be implemented and verified in this repository"
        - "Yes: blocked on hardware / customer data / external decision"
  - type: textarea
    attributes:
      label: Additional context
      description: Open questions (OQ-XXX), related issues, or notes for the reviewer.
---
