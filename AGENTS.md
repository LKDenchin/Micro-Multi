# AGENTS.md

> **Project Engineering Constitution**  
> This document defines how AI agents collaborate, develop, review, validate, and integrate software in this project.

---

## 1. Project Mission

This project is an **open-source, model-agnostic Multi-Agent Software Engineering Platform**.

Its purpose is not simply to make an AI write more code. The core objective is to enable multiple AI agents to work together as a reliable software engineering team through:

- Contract-first collaboration
- Dependency-aware parallel development
- Isolated workspaces and Git-based state management
- Multi-layer code review
- Automated executable verification
- Automatic repair and retry
- Full traceability and reproducibility
- Pluggable models, agents, tools, and workflows

### Core principle

> **LLM generates proposals; contracts constrain them; tools execute them; evidence verifies them.**

An agent must never be treated as the final authority on whether software is correct merely because the model claims that it is correct.

---

# 2. Product Positioning

The project should be understood as:

> **Infrastructure for Contract-driven Multi-Agent Software Engineering.**

It is not primarily:

- A chat interface for coding
- A single-agent IDE assistant
- A collection of independent coding prompts
- A hard-coded "AI software company" role-play system

The system must focus on the engineering problems created by **multiple autonomous agents modifying the same software project**.

The major engineering questions are:

1. How can tasks be decomposed into safely parallelizable units?
2. How can agents share a stable contract without contaminating each other's context?
3. How can module conflicts be detected before integration?
4. How can agent-generated code be independently verified?
5. How can failed work be repaired automatically without losing traceability?
6. How can an entire execution be replayed and reproduced?
7. How can different models and agents be exchanged without changing the workflow core?

---

# 3. Design Principles

## 3.1 Contract First

Every non-trivial engineering task must be grounded in an explicit project contract.

The contract may include:

- API definitions
- Data schemas
- Type definitions
- Module boundaries
- Dependency constraints
- Input/output contracts
- Error behavior
- Security requirements
- Testing requirements
- Project coding standards

Agents must **read the contract before implementation**.

Agents must not silently redefine shared interfaces.

When a contract must change, the change must go through an explicit contract update process and trigger re-validation of affected tasks.

---

## 3.2 Evidence Over Claims

Statements such as:

- "The code should work."
- "The bug is fixed."
- "The tests should pass."
- "The API is compatible."

are not sufficient evidence.

Acceptance must be based on executable or otherwise machine-checkable evidence whenever practical:

- Build result
- Unit test result
- Integration test result
- Static analysis result
- Type checking result
- Security scan result
- Contract validation result
- Runtime health check

A reviewer may identify a suspected problem, but a passing review alone does not prove correctness.

---

## 3.3 Isolation Before Parallelism

Parallel work is allowed only when each task has an isolated execution context.

Preferred isolation mechanisms include:

- Git branches
- Git worktrees
- Containerized workspaces
- Independent temporary directories
- Independent agent sessions

Agents must not casually modify another agent's working tree.

Shared mutable state must be minimized.

---

## 3.4 Explicit Dependencies

Tasks must declare dependencies explicitly.

Use a dependency graph or DAG whenever possible.

Example:

```text
TASK-001 Architecture
   ├──> TASK-002 Backend API
   ├──> TASK-003 Database Layer
   └──> TASK-004 Frontend
             │
             └──> TASK-005 Integration
```

A task should be parallelized only when its required inputs are already stable.

---

## 3.5 Small, Reviewable Changes

Agents should prefer small, focused commits over large mixed changes.

Each commit should ideally represent one coherent engineering intent.

Avoid combining unrelated changes such as:

```text
feature + refactor + formatting + dependency update
```

unless explicitly required by the task.

---

## 3.6 Deterministic Where Possible

Agent behavior is inherently probabilistic, but the surrounding engineering system should be deterministic whenever practical.

The system should record:

- Model name and version
- Prompt / task specification
- Agent configuration
- Tool versions
- Relevant environment variables
- Repository revision
- Contract revision
- Random seed where supported
- Tool inputs and outputs
- Test commands
- Build commands
- Result artifacts

An execution should be reproducible or, when full reproduction is impossible, diagnosable from its trace.

---

## 3.7 Model Agnostic

The orchestration layer must not depend on one specific model provider.

The system should support, through adapters or standardized interfaces where practical:

- Hosted API models
- Open-source models
- Local inference
- Fine-tuned models
- Specialized coding models
- Specialized review/security models

Changing the model should not require redesigning the workflow engine.

---

## 3.8 Tool Agnostic

Tools are capabilities, not business logic.

The platform should treat tools through explicit adapters/interfaces whenever practical.

Potential tool categories include:

- Shell
- Git
- Build systems
- Test runners
- Linters
- Type checkers
- Static analyzers
- Security scanners
- Package managers
- Databases
- Browsers
- Documentation systems

A tool failure must be distinguishable from an agent reasoning failure.

---

# 4. Agent Roles

The platform uses role specialization, but roles must remain modular and replaceable.

## 4.1 Planner Agent

Responsibilities:

- Understand user requirements
- Extract constraints and acceptance criteria
- Decompose the project into tasks
- Identify task dependencies
- Propose module boundaries
- Produce or update the project execution plan

The Planner must not invent implementation details that contradict the project contract.

Output should be structured and machine-readable whenever practical.

---

## 4.2 Contract Agent / Contract Registry

Responsibilities:

- Maintain the canonical project contract
- Register APIs and schemas
- Record module boundaries
- Track dependency relationships
- Detect incompatible contract changes
- Version contract revisions

The Contract Registry is the authoritative source for shared interfaces.

The source of truth must not be an individual agent's conversation history.

---

## 4.3 Coder Agent

Responsibilities:

- Implement one assigned task/module
- Follow the project contract
- Write or update tests
- Avoid unrelated modifications
- Produce a concise change summary
- Return structured implementation metadata

The Coder Agent must operate inside an isolated workspace.

The Coder Agent must not declare a task complete solely from model self-assessment.

---

## 4.4 Reviewer Agents

Reviewers should be specialized where useful.

Possible reviewers:

### Logic Reviewer

Checks:

- Business logic
- Edge cases
- State transitions
- Error handling
- Algorithmic correctness

### Contract/API Reviewer

Checks:

- Request/response compatibility
- Type compatibility
- Schema compatibility
- Naming consistency
- Dependency assumptions

### Security Reviewer

Checks:

- Authentication and authorization
- Injection risks
- Secret handling
- Input validation
- Unsafe file/network/process operations
- Dependency/security concerns

### Quality Reviewer

Checks:

- Maintainability
- Complexity
- Duplication
- Readability
- Project conventions

Reviewers should return findings with severity, evidence, and recommended action.

---

## 4.5 Verification Agent

The Verification Agent coordinates executable checks.

Preferred verification order:

```text
Contract Validation
      ↓
Static Analysis
      ↓
Build / Compile
      ↓
Unit Tests
      ↓
Integration Tests
      ↓
Security Checks
      ↓
Runtime / Smoke Tests
```

The exact pipeline depends on the project type.

Verification must return machine-readable results whenever practical.

---

## 4.6 Repair Agent

Responsibilities:

- Analyze failed verification results
- Identify the likely root cause
- Produce a minimal repair
- Re-run relevant checks
- Avoid introducing unrelated changes

Repair should operate on evidence from the failed run rather than blindly regenerating the entire module.

---

## 4.7 Integration / Merge Agent

Responsibilities:

- Collect validated task branches
- Detect merge conflicts
- Re-check contracts after integration
- Trigger integration tests
- Produce the final merge candidate

The Merge Agent must never bypass failed mandatory verification checks merely to obtain a successful merge.

---

# 5. Standard Agent Lifecycle

Every engineering task should follow this lifecycle unless the workflow explicitly overrides it:

```text
Receive Task
    ↓
Load Context
    ↓
Load Contract
    ↓
Inspect Relevant Repository State
    ↓
Plan Local Changes
    ↓
Implement
    ↓
Run Local Verification
    ↓
Commit / Publish Artifact
    ↓
Review
    ↓
Automated Verification
    ↓
PASS ───────────────→ Integration
    │
    └─ FAIL → Repair → Re-verify
```

A task must have a clear terminal state:

- `SUCCESS`
- `FAILED`
- `BLOCKED`
- `CANCELLED`

Never represent an unresolved state as successful merely because generation completed.

---

# 6. Task Specification

Every task should contain enough structured information for an agent to work independently.

Example:

```yaml
id: TASK-012
name: Implement user authentication API
status: pending
owner: coder-backend
priority: high

inputs:
  - contract: contracts/auth-api.yaml
  - module: backend/auth

dependencies:
  - TASK-003

constraints:
  - Use project authentication interface
  - Do not modify public API without contract change
  - Add unit tests

acceptance_criteria:
  - Login endpoint implemented
  - Invalid credentials return expected error
  - Unit tests pass
  - API contract validation passes
```

---

# 7. Contract Rules

## 7.1 Single Source of Truth

Shared interface definitions must live in the canonical contract layer.

Do not rely on:

- Hidden prompt assumptions
- Agent memory
- Untracked local notes
- Informal chat messages

---

## 7.2 Contract Changes Are Versioned

A contract change should record:

```text
who / which agent
what changed
why it changed
which tasks are affected
what verification must be repeated
```

Breaking changes should trigger explicit dependency analysis.

---

## 7.3 Contract Compatibility Must Be Machine-Checkable

Where practical, contracts should be validated automatically.

Examples:

- OpenAPI validation
- JSON Schema validation
- Protocol Buffers compatibility checks
- Type checking
- Generated client/server compatibility tests

---

# 8. Parallel Scheduling

Parallelization must be dependency-aware.

The Scheduler should distinguish at least:

```text
READY
RUNNING
BLOCKED
WAITING_REVIEW
WAITING_VERIFICATION
REPAIRING
INTEGRATION_READY
SUCCESS
FAILED
```

A task can execute in parallel with another task only when their required shared resources and contract dependencies permit it.

The Scheduler should aim to maximize useful parallelism, not raw agent count.

### Core principle

> **More agents do not automatically mean more throughput.**

The system should be able to measure when coordination overhead begins to exceed parallelism benefits.

---

# 9. Workspace and Git Rules

Each coding task should operate in an isolated Git workspace.

Preferred structure:

```text
main
├── agent/TASK-001
├── agent/TASK-002
├── agent/TASK-003
└── agent/TASK-004
```

Agents should:

1. Start from a known repository revision.
2. Work only inside their assigned workspace.
3. Make focused commits.
4. Preserve testable intermediate states.
5. Report changed files and commit identifiers.
6. Never force-push shared branches unless explicitly authorized.
7. Never destroy another agent's work.

Merge conflicts must be surfaced explicitly.

---

# 10. Review Rules

Review findings should be structured.

Recommended format:

```json
{
  "severity": "high",
  "category": "contract",
  "file": "backend/auth.py",
  "line": 87,
  "finding": "Return type does not match authentication contract",
  "evidence": "Expected AuthResponse, implementation returns User",
  "action": "Change return type and update corresponding test"
}
```

Severity should be consistent across the system, for example:

```text
BLOCKER
HIGH
MEDIUM
LOW
INFO
```

Do not use review scores as the sole merge criterion.

A numerical score is a supplementary signal, not evidence of correctness.

---

# 11. Verification Rules

Verification should be layered.

## Layer 1: Contract

Check that the implementation conforms to defined interfaces.

## Layer 2: Static

Run applicable:

- Formatter
- Linter
- Type checker
- Static analyzer

## Layer 3: Build

Compile/build the affected project.

## Layer 4: Unit Tests

Run tests closest to the modified code.

## Layer 5: Integration Tests

Verify interactions among modules.

## Layer 6: Security

Run applicable security checks.

## Layer 7: Runtime

Run smoke tests or health checks where applicable.

A project may define mandatory gates for each layer.

---

# 12. Failure and Repair Policy

A failure should preserve its evidence.

When a task fails, record:

- Failed command
- Exit code
- Relevant logs
- Agent context
- Changed files
- Contract revision
- Environment information
- Review findings

Repair agents should receive the relevant failure evidence.

Avoid this pattern:

```text
Failure
 ↓
Regenerate entire project
```

Prefer:

```text
Failure
 ↓
Diagnose
 ↓
Patch minimal cause
 ↓
Targeted verification
 ↓
Full verification when necessary
```

Retry loops must have explicit limits.

---

# 13. Human-in-the-Loop

The platform must support optional human checkpoints.

Humans should be able to approve:

- Contract changes
- Security-sensitive changes
- Destructive operations
- Dependency upgrades
- Merge operations
- Release operations

The system should not assume that full autonomy is always desirable.

Human approval should be a first-class workflow node, not a special-case workaround.

---

# 14. Observability and Trace

Every run should produce a traceable execution record.

Minimum trace fields should include:

```text
run_id
task_id
agent_id
model
model_version
prompt_version
contract_version
repository_revision
tool_calls
tool_outputs
changed_files
commit_id
review_results
verification_results
timestamps
final_status
```

The trace system should make it possible to answer:

- What did the agent receive?
- What did it change?
- Which tools did it use?
- Which reviewer rejected it?
- Which test failed?
- What repair was performed?
- Why was the final artifact accepted?

---

# 15. Replay and Reproducibility

The platform should provide a replay mechanism for completed runs where technically feasible.

Replay should restore, as closely as practical:

- Repository revision
- Contract revision
- Agent configuration
- Model configuration
- Tool configuration
- Task input
- Relevant tool inputs

Because model outputs can change between runs, the system should distinguish:

```text
Exact Replay
```

from

```text
Logical Replay / Re-execution
```

Exact replay may require cached model/tool outputs or deterministic fixtures.

---

# 16. Security Rules

Agents must be treated as untrusted executors by default.

Sensitive capabilities should be isolated and permissioned.

Prefer:

- Sandboxed execution
- Containerization
- Least privilege
- Explicit filesystem permissions
- Explicit network permissions
- Secret isolation
- Command allow/deny policies

Never expose secrets to an agent unless required by the task and explicitly authorized.

Never log credentials, API keys, tokens, or private secrets.

Destructive operations require explicit policy controls.

---

# 17. API and Internal Interfaces

Internal interfaces should be explicit and versioned.

Prefer structured messages over free-form text for system-to-system communication.

Example envelope:

```json
{
  "message_id": "msg-123",
  "run_id": "run-456",
  "task_id": "TASK-012",
  "sender": "coder-backend",
  "recipient": "reviewer-api",
  "type": "review.request",
  "contract_version": "v3",
  "payload": {}
}
```

Messages should be:

- Validatable
- Traceable
- Versioned
- Backward-compatible where practical

---

# 18. Configuration and Extensibility

New models, agents, tools, and workflows should be added through extension points rather than modifying the core orchestration logic.

Conceptually:

```text
Core
├── Agent Runtime
├── Scheduler
├── Contract Engine
├── Workspace/Git Engine
├── Verification Engine
└── Trace Engine

Plugins / Adapters
├── Model Providers
├── Agent Implementations
├── Tool Adapters
├── Review Strategies
└── Workflow Strategies
```

The core should remain small.

---

# 19. Repository Organization

A recommended repository layout is:

```text
.
├── AGENTS.md
├── README.md
├── LICENSE
├── pyproject.toml
├── docs/
├── examples/
├── src/
│   └── platform/
│       ├── agents/
│       ├── orchestration/
│       ├── contracts/
│       ├── scheduler/
│       ├── workspace/
│       ├── verification/
│       ├── review/
│       ├── trace/
│       ├── adapters/
│       └── cli/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── system/
│   └── benchmarks/
├── examples/
├── contracts/
├── workflows/
└── scripts/
```

The exact layout may evolve, but boundaries between core subsystems should remain explicit.

---

# 20. Coding Standards for Agents

Agents must:

- Read relevant existing code before editing.
- Reuse existing abstractions when appropriate.
- Avoid unnecessary dependencies.
- Keep functions/modules focused.
- Add tests for behavior changes.
- Update documentation for public interfaces.
- Preserve backward compatibility unless the task explicitly changes it.
- Avoid unrelated formatting churn.
- Report uncertainty explicitly.

Agents must not:

- Pretend to have executed a command they did not execute.
- Claim tests passed without actual test evidence.
- Invent API behavior.
- Silently ignore contract violations.
- Delete unrelated work.
- Modify shared configuration without justification.
- Hide verification failures.

---

# 21. Documentation Standards

Every public subsystem should document:

1. Purpose
2. Inputs
3. Outputs
4. Configuration
5. Extension points
6. Failure modes
7. Example usage

Architecture decisions should be recorded when a decision has long-term impact.

Prefer concise Architecture Decision Records (ADRs) for major design choices.

---

# 22. Testing Strategy

The project itself is a software engineering platform, so its own engineering quality is critical.

Testing should include:

### Unit Tests

Test individual components.

### Integration Tests

Test interactions among:

- Planner
- Scheduler
- Contract Engine
- Agent Runtime
- Verification Engine

### System Tests

Run complete end-to-end workflows.

### Failure Injection

Intentionally create:

- API mismatches
- Merge conflicts
- Test failures
- Tool failures
- Invalid contracts
- Reviewer false positives
- Reviewer false negatives

The platform should recover or fail clearly.

### Benchmark Tests

Track system performance on fixed tasks.

---

# 23. Evaluation Metrics

The project should support quantitative evaluation.

Recommended metrics include:

## Task Success Rate

```text
successful tasks / total tasks
```

## Build Success Rate

```text
successful builds / total build attempts
```

## Test Pass Rate

```text
passed tests / executed tests
```

## Defect Detection Rate

```text
correctly detected defects / actual defects
```

## False Positive Rate

```text
incorrect review findings / total review findings
```

## Repair Success Rate

```text
successfully repaired failures / repair attempts
```

## Contract Conflict Rate

```text
contract conflicts / integration attempts
```

## Parallel Efficiency

Measure useful work gained from additional agents relative to:

- Execution time
- Coordination overhead
- Token usage
- Conflict rate

## Cost Efficiency

Record model/tool consumption where possible.

The project must avoid optimizing one metric while silently degrading critical correctness metrics.

---

# 24. Benchmark and Research Protocol

The framework should support controlled comparisons such as:

```text
Single Agent
vs.
Multi-Agent
```

```text
Multi-Agent
vs.
Multi-Agent + Review
```

```text
No Contract
vs.
Contract-First
```

```text
LLM Review
vs.
LLM Review + Executable Verification
```

```text
1 Agent
2 Agents
4 Agents
8 Agents
16 Agents
```

Experiments should keep task sets, environments, and evaluation methods consistent.

Do not claim an improvement without reporting the corresponding evaluation conditions.

---

# 25. Open-Source Principles

This project is intended to become a reusable open-source platform, not a one-off demo.

Prioritize:

- Clear documentation
- Reproducible examples
- Stable extension APIs
- Transparent benchmarks
- Issue-friendly architecture
- Contributor onboarding
- Backward-compatible interfaces where practical
- Human-readable logs
- License compliance

Avoid unnecessary vendor lock-in.

Community contributors should be able to add:

- New models
- New agent roles
- New tools
- New verification strategies
- New workflows
- New benchmark tasks

without learning the entire codebase.

---

# 26. Definition of Done

A task is considered **DONE** only when all required conditions are satisfied.

Typical conditions:

```text
[ ] Requirements understood
[ ] Contract loaded
[ ] Dependencies satisfied
[ ] Implementation completed
[ ] Tests added/updated
[ ] Static checks passed
[ ] Build passed
[ ] Required tests passed
[ ] Review passed
[ ] Contract validation passed
[ ] Changes committed
[ ] Trace recorded
[ ] Documentation updated when needed
```

A generated patch is not equivalent to a completed software task.

---

# 27. Decision Hierarchy

When instructions conflict, use this priority order:

```text
1. Safety / Security Constraints
2. Explicit User Requirements
3. Project Contract
4. Repository Architecture / Established Interfaces
5. Task Specification
6. Agent Local Preferences
```

An agent's convenience must never override a higher-level contract.

---

# 28. Final Engineering Rule

The system exists to turn autonomous generation into reliable engineering.

Therefore:

```text
Generate
   ↓
Constrain
   ↓
Isolate
   ↓
Review
   ↓
Execute
   ↓
Measure
   ↓
Repair
   ↓
Verify
   ↓
Integrate
   ↓
Record
```

> **Code is an artifact. Evidence is the acceptance criterion.**

This principle should guide architecture, implementation, evaluation, and future extensions of the project.
