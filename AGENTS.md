# AssemblyVision Coding Rules

## 1. Language

English is the official language of this repository.

The following must be written in English:

- Source code
- Documentation
- README files
- Code comments
- Docstrings
- API documentation
- Commit messages
- Pull request descriptions

## 2. Required Reading

Before making changes:

1. Read the relevant files under `docs/design/`.
2. Read the relevant contracts under `docs/contracts/`.
3. Read related ADRs under `docs/design/decisions/`.
4. Inspect existing interfaces, implementations, and tests.
5. Use `docs/ai/context.md` when broader repository context is required.

Documentation hierarchy:

```text
docs/design/             Defines how the system is designed.
docs/design/decisions/   Explains why major decisions were made.
docs/contracts/          Defines mandatory implementation constraints.
docs/runbooks/           Defines operational recovery procedures.
```

If documents conflict, use this precedence:

```text
Explicit user instruction
→ Accepted ADR
→ Engineering contract
→ Architecture design
→ Existing implementation
```

Report conflicts before changing public architecture or behavior.

## 3. Architecture Rules

1. Preserve the documented edge-first architecture.
2. Do not introduce new frameworks or services without justification.
3. Keep AI inference, rule evaluation, persistence, and Web APIs separated.
4. Do not put YOLO inference logic inside FastAPI route handlers.
5. Do not put business rules inside AI models or detector classes.
6. Do not let the edge inspection pipeline depend on the central server.
7. Maintain offline operation and persistent upload retry behavior.
8. Do not bypass the Rule Engine.
9. Respect `docs/contracts/01-architecture-boundaries.md`.
10. Prefer the smallest complete implementation over speculative abstractions.

## 4. Safety Rules

1. Never return `OK` when inspection evidence is incomplete or invalid.
2. Detector failures, invalid ROI, missing rules, unknown product types, and unavailable models must produce `NG` or `UNCERTAIN` according to policy.
3. Never claim the inspection system guarantees 100% accuracy.
4. Preserve the original AI decision during human review.
5. Do not delete local media until upload and retention conditions are satisfied.

## 5. Code and Interface Rules

1. Use explicit type annotations for public functions and classes.
2. Use typed Pydantic models for backend contracts.
3. Use generated or synchronized TypeScript API types.
4. Do not use unstructured dictionaries as core domain interfaces.
5. Do not change public interfaces silently.
6. Do not add placeholder implementations unless clearly marked.
7. Report unresolved assumptions and hardware dependencies.

### 5.1 Comments and Docstrings

1. Let clear names, types, structure, and tests explain ordinary behavior.
2. Use comments only for non-obvious rationale: safety invariants, industrial or hardware assumptions, units or coordinate-space rules, failure semantics, reproducibility constraints, external-library quirks, and deliberate temporary limitations.
3. Do not restate code, narrate control flow, retain commented-out code, or add vague `TODO` or `FIXME` notes.
4. Put cross-module or long-lived rationale in design documents or ADRs; source comments should remain short and link there when needed.
5. Update or remove a comment when its associated behavior changes.

## 6. Quality Rules

For every behavioral change:

1. Add or update tests.
2. Run Ruff.
3. Run MyPy.
4. Run Pytest.
5. Report the exact commands executed.
6. Do not claim checks passed unless they were actually executed.
7. Report failures that could not be resolved.

## 7. Documentation Rules

Update relevant documentation when changing:

- Architecture
- Public APIs
- Database schemas
- Module interfaces
- Configuration formats
- Deployment behavior
- Model manifests
- Rule formats
- Operational recovery behavior

Documentation is part of the implementation.

## 8. Git Workflow

### 8.1 Conventional Commits

Commit messages must follow Conventional Commits:

- `feat:`
- `fix:`
- `docs:`
- `refactor:`
- `test:`
- `build:`
- `ci:`
- `chore:`

### 8.2 Branch Naming

Use:

- `feat/...`
- `fix/...`
- `docs/...`
- `refactor/...`
- `chore/...`

### 8.3 Commit and Push Policy

- Do not create commits unless explicitly requested.
- Do not push unless explicitly approved.
- Do not force-push unless explicitly requested.
- Do not rewrite Git history without explicit approval.

## 9. Security

- Never commit secrets.
- Never hardcode credentials, tokens, or private keys.
- Do not expose stack traces, internal paths, or credentials through APIs.
- Use environment-based runtime configuration.
