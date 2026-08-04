# AssemblyVision Coding Rules

Before implementing any feature:

1. Read the relevant files under `docs/`.
2. Inspect existing interfaces and tests.
3. Preserve the documented edge-first architecture.
4. Do not introduce new frameworks or services without justification.
5. Keep AI inference, rule evaluation, persistence, and Web APIs separated.
6. Do not put YOLO inference logic inside FastAPI route handlers.
7. Do not put business rules inside the AI model.
8. Do not let the edge inspection pipeline depend on the central server.
9. Maintain offline operation and upload retry behavior.
10. Use typed Pydantic models and TypeScript interfaces.
11. Add or update tests for every behavioral change.
12. Run tests, Ruff, and MyPy before completing a task.
13. Do not claim tests passed unless they were actually executed.
14. Do not change public interfaces silently.
15. Do not add placeholder implementations unless clearly marked.
16. Report unresolved assumptions and hardware dependencies.
17. Prefer the smallest complete implementation over speculative abstractions.
18. Never claim the inspection system guarantees 100% accuracy.