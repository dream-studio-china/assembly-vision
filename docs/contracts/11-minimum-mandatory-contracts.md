# 11. Minimum Mandatory Contracts

AssemblyVision must enforce the following rules whenever their subsystem is in scope. Rules 1-9,
13-17, and 19 apply from the static spike; upload, database, API, TypeScript, audit, and cleanup
rules activate when those subsystems are introduced:

1. All Python code passes Ruff.
2. All core modules pass MyPy.
3. Core business logic is covered by Pytest.
4. FastAPI routes do not call YOLO directly.
5. Detectors do not decide `OK` or `NG`.
6. The Rule Engine does not depend on YOLO, the database, or FastAPI.
7. Edge inspection does not depend on the central server.
8. Incomplete or invalid evidence never defaults to `OK`.
9. Every inspection records model and rule versions.
10. All upload operations are idempotent.
11. Data that has not been uploaded is not deleted locally.
12. Models and rules support rollback.
13. Human review does not overwrite the original AI result.
14. Camera or lighting changes require revalidation.
15. The system must not claim guaranteed 100% accuracy.
16. A missing model prevents the service from entering the Ready state.
17. Missing product configuration or rules must not produce `OK`.
18. All database schema changes use Alembic.
19. Production configuration is not hardcoded in business logic.
20. Public APIs are versioned.
21. Python and TypeScript types are synchronized through OpenAPI.
22. Critical configuration changes are audited.
23. Customer acceptance data is not taken from the training set.
24. Duplicate uploads do not create duplicate central records.
25. Local media cleanup checks both upload status and active references.

## Related Documents

- [Contract index](./README.md)
- [Appendices - decision consistency checklist](../design/appendices.md#2-decision-consistency-checklist)
- [Contributor rules](../contributing.md)
