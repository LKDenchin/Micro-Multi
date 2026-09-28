# MVP acceptance record

Status: complete for the local fixture workflow. Date: 2026-09-28.

## Coverage

Built against PRODUCT_DEVELOPMENT_SPEC.md v1.0 sections 25, 40, 45 and 46. Includes the
standalone web UI / REST / SSE / CLI, project creation and local Git import, Planner, versioned
Contract, DAG and resource-aware scheduling, Coder / Reviewer / Repair, isolated worktrees,
layered verification, restricted Docker runner, final verification, fast-forward merge,
ZIP artifact, SQLite trace, history / replay viewing, pause / resume / cancel, and a fixed
fault-injection benchmark.

## Executed evidence

Environment: Windows 10, Python 3.14.7, Git 2.53.0.

| Check | Result |
| --- | --- |
| `python -m ruff check src tests scripts` | Pass |
| `python -m ruff format --check src tests scripts` | Pass |
| `python -m mypy src/masp` | Pass, 11 source files |
| `python -m compileall -q src` | Pass |
| `python -m pytest -q` | **41 passed, 1 skipped** |
| `python -m build` | Wheel and sdist built successfully |
| `python scripts/benchmark.py --workers 1 2 4 --output evidence/benchmark.json` | 3/3 runs passed; see [benchmark.json](../evidence/benchmark.json) |

The end-to-end run created two isolated Git worktrees. The subtract unit gate failed on its
first attempt. The repair agent received the failure evidence, fixed the implementation, and
passed the next verification. Both commits entered a candidate branch; the final integration
gate passed before the managed repository was merged and a ZIP artifact was created. The test
then executed the two generated unittest cases independently from that artifact.

The benchmark holds the two-task plan and injected defect constant, uses one sample per worker
setting, makes no external model calls, and includes project/Git setup time. Windows measured
5387 / 4134 / 5060 ms at 1 / 2 / 4 workers. This small synthetic benchmark does not establish a
general throughput or performance claim. Recorded tokens were zero; cost correctly remains unknown.

## Skips and limitations

- One symlink traversal test was skipped because this Windows account cannot create symlinks.
  Other tests cover traversal paths, out-of-scope file writes, and case collisions. Linux CI
  exercises the symlink test.
- Docker is unavailable on this host. **Real-model Docker execution and actual container
  isolation have not been exercised.** The runner refuses host fallback and its fail-closed
  configuration is unit tested.
- No live model endpoint or API credential was configured. Verified runs use the fixture only.
- This run built on Windows / Python 3.14. A Python 3.11 / Linux CI matrix is configured but
  was not run during this session.
- The section 46 deterministic acceptance path is complete. General requirement planning depends
  on the configured model and needs later evaluation on a fixed, multi-run task set.
- Web/API is a local single-user MVP. It does not provide public authentication, remote Git URL
  import, automatic conflict repair, exact cached replay, multi-tenancy, or priced billing.
  See the [security model](sandbox.md) and [deployment guide](deployment.md).
- The browser was used to verify the rendered dashboard. REST, SSE and static assets were tested
  through FastAPI's API client; application workflows were verified through system tests.

Conclusion: the requested, reproducible local MVP flow passed executable checks. Docker,
real-model, and cross-platform runtime verification still require their respective environments.
