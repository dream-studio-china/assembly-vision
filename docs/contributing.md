# Contributing to AssemblyVision

## 1. Required Reading

Before changing implementation or public behavior:

1. Read the relevant [design documents](design/README.md).
2. Read the relevant [engineering contracts](contracts/README.md).
3. Read related [architecture decisions](design/decisions/README.md).
4. Use the [AI context snapshot](ai/context.md) when broader context is required.

The authoritative repository rules are in
[AGENTS.md](https://github.com/dream-studio-china/assembly-vision/blob/main/AGENTS.md).

## 2. Documentation Precedence

```text
Explicit user instruction
-> Accepted ADR
-> Engineering contract
-> Architecture design
-> Existing implementation
```

Report conflicts before changing public architecture or behavior.

## 3. Language and Git

- Source, documentation, comments, API documentation, README files, commits, and pull requests use English.
- Use Conventional Commits and the documented branch prefixes.
- Do not commit secrets or generated runtime data.
- Do not commit, push, force-push, or rewrite history without explicit approval.

## 4. Quality

Behavioral changes require tests and the applicable Ruff, MyPy, Pytest, API-contract, frontend,
model-evaluation, and resilience checks defined in the engineering contracts. Report exact commands
and unresolved failures; never claim an unexecuted check passed.
