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
        - Backend API / persistence / upload
        - Training and dataset tooling
        - Camera / barcode hardware integration
        - Documentation
        - Infrastructure / CI / packaging
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
      description: Concrete, testable outcomes. Fail-safe and NG/UNCERTAIN behavior must be explicit where decisions are involved.
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
