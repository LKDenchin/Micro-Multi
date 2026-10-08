# Multi-agent collaboration

Team mode is Micro-Multi's main execution workflow. The lead prepares the plan and combines results. Members take implementation, tests, documentation or review. The scheduler handles concurrency, dependencies, file ownership and duplicate dispatch. You decide whether the plan runs.

## Review the plan

Choose multi-agent collaboration in the composer and describe the task, constraints and acceptance criteria. During preparation, the lead reads relevant material and writes requirement, design and task documents. Members do not start until you confirm the plan.

The plan card lists the proposed team. Open Adjust team to edit roles, prompts, assigned files and models. Check that the responsibilities fit the task and that members are not making conflicting changes to the same files. Then choose Confirm execution to start the displayed version. A new task or round of feedback produces another plan and needs another confirmation.

The card can arrive while the planning turn is still saving. Confirmation waits for that turn to finish, then checks the server revision. A stale local cache does not block a valid plan. If the server has a newer revision, the card updates in place for another review and confirmation. A consumed approval cannot start the revision again or silently trigger another planning round.

## Parallel tasks and dependencies

Independent assignments run within a concurrency limit. `depends_on` makes a task wait for predecessor reports. A failed predecessor stops dependent work. Do not run sequential writes together just to call them parallel.

For example, an API member edits `api.py` while a documentation member updates `docs/api.md`. Integration tests depend on the API work and should wait for its report. Members declare files through `owned_paths`; reservations and path locks coordinate the shared workspace. Dependent members can handle successive stages in the same file.

Enabled DeepSeek Harness plugin tools, MCP services and command tools are available to the lead and members. Plugins do not need a separate installation for every member. Members retain their model configuration and current permissions. See [native dsh plugins](NATIVE_CORDIS.md).

## Follow execution

Members follow the lead model unless you select a different one. Their assignments, status and reports appear in the team view. Tool records show file operations, commands and extension calls, including any approvals.

You can send additional instructions while the team works. Pause the conversation when you need to inspect the current state, or stop it to end execution. The lead can remove a failed member before trying another approach; removal cancels that member's work and releases its file reservations.

## Check the result

After the members report back, inspect the resulting files, diffs and validation output. A member's completion report is not a substitute for a successful test or review. If something is missing, explain it in a follow-up and review the next plan.

Plan records are stored in `.masp/team-plans/` within the workspace, and plan cards remain in the conversation history. For an example task with implementation and test roles, see [task examples](../PRODUCT_DEVELOPMENT_SPEC.md).

More members are not always better. Use the lead alone for a short task, and a team when responsibilities are clear and work can run in parallel. Extra members may increase model cost. See [Agent design and tradeoffs](AGENT_DESIGN.md).
