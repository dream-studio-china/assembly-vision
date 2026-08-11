---
name: Bug report
description: Report a defect in the AssemblyVision edge runtime, dashboard, training tooling, or documentation
title: "[bug]: "
labels: ["bug", "triage"]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for reporting a bug. Please fill in as much detail as possible.
        Before you start, review the relevant [engineering contracts](https://github.com/dream-studio-china/assembly-vision/tree/main/docs/contracts) and note any contract you believe is violated.
  - type: dropdown
    attributes:
      label: Component
      description: Which part of the repository is affected?
      options:
        - edge-service (inspect/verify/serve, pipeline, rules, detectors)
        - edge-web (Vue operator dashboard)
        - edge-desktop (Electron shell)
        - api-client / ui (TypeScript packages)
        - domain / vision-core (Python packages)
        - training (av-train CLI)
        - camera / barcode / trigger (GigE/GenICam, ZXing decode, Modbus FIFO)
        - scripts (dataset adapters, e2e demo)
        - docs (design, contracts, runbooks, reviews)
    validations:
      required: true
  - type: dropdown
    attributes:
      label: Severity
      description: Match the P0-P3 finding convention used in docs/reviews/.
      options:
        - "P0: blocks the current milestone or is a safety-critical defect"
        - "P1: high impact, should be fixed soon"
        - "P2: moderate impact"
        - "P3: low impact or cosmetic"
    validations:
      required: true
  - type: dropdown
    attributes:
      label: Safety impact
      description: Does this defect affect the inspection decision (OK/NG) or the false-negative rate?
      options:
        - "None: developer tooling or cosmetics only"
        - "Uncertain: may affect decision correctness"
        - "Yes: can produce incorrect OK/NG or raise false-negative risk"
    validations:
      required: true
  - type: dropdown
    attributes:
      label: Production impact
      description: Which production gate or acceptance phase does this affect (E1-E6)?
      options:
        - "None: developer tooling, tests, or cosmetics"
        - "E1-E5: runtime, storage, upload, observability, or deployment behavior"
        - "E6: on-site acceptance evidence or held-out customer model validation"
        - "Uncertain"
    validations:
      required: true
  - type: textarea
    attributes:
      label: Describe the bug
      description: What happened, and what was expected? Include the exact error, NG/UNCERTAIN reason code, or HTTP problem code where applicable.
      placeholder: "Example: `assemblyvision verify` exits 0 with skipped expected samples..."
    validations:
      required: true
  - type: textarea
    attributes:
      label: Steps to reproduce
      description: Provide the exact commands (e.g. `uv run assemblyvision inspect ...`) and configuration files used.
      placeholder: |
        1. ...
        2. ...
        3. ...
    validations:
      required: true
  - type: textarea
    attributes:
      label: Expected vs actual
      description: Contrast the expected behavior with the observed behavior.
    validations:
      required: true
  - type: input
    attributes:
      label: Model and rule versions
      description: Model manifest names/versions and the rule id/version in use, if applicable.
      placeholder: "product: v1.2.0, components: v1.0.1, rule: sample-rule/1"
  - type: input
    attributes:
      label: Related runbook
      description: If this is an operational failure, which runbook scenario applies (docs/runbooks/01..15)?
      placeholder: "runbook 05 (database recovery)"
  - type: textarea
    attributes:
      label: Environment
      description: OS, Python/uv version, Node/pnpm version, GPU, and camera/hardware if relevant.
      placeholder: "macOS 14 / Python 3.12 / uv 0.5 / Node 22 / Apple Silicon"
  - type: textarea
    attributes:
      label: Evidence
      description: Log excerpts, inspection bundle IDs, screenshots, or repro scripts. Do not paste secrets, model weights, or production media.
  - type: checkboxes
    attributes:
      label: Quality gates
      description: If you ran any checks, which ones did you run and do they pass?
      options:
        - label: "`make check` (ruff, mypy, pytest, frontend gates)"
        - label: "OpenAPI / TypeScript contract drift checks"
        - label: "Playwright e2e"
        - label: "`uv run mkdocs build --strict` (docs)"
  - type: textarea
    attributes:
      label: Additional context
      description: Any related design document, ADR, contract, runbook, open question (OQ-XXX), or prior review finding (PR-003..PR-031, AUDIT-001).
---
