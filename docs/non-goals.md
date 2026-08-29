# Non-goals

The following non-goals are enforced by `tests/test_non_goals.py`, not by review discipline alone:

1. **No plugin system** — the eval harness is not extensible via discovery or entry points.
2. **No generic task abstraction** — this repository solves one task only. Task-parameterisation code, a task registry, or a multi-task runner cannot land.
3. **No multi-tenant SaaS** — no shared accounts, shared workspaces, or usage quotas.
4. **No "bring your own eval"** — users cannot ingest arbitrary metrics, scoring functions, or test cases.
5. **No observability product** — results are not a telemetry backend or a model performance dashboard.
6. **No prompt management** — judge prompts are reviewed, versioned, and fixed by humans, never dynamically constructed or loaded.

These boundaries keep the project vertical and concrete — one task, one golden set, published methodology. They are AST-checked at CI time and cannot be violated in a commit.
