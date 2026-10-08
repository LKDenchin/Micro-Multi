# Agent design and tradeoffs

Micro-Multi puts collaboration in the execution layer. The lead understands the job and proposes assignments. The scheduler handles approved revisions, dependencies, file reservations and duplicate execution. DeepSeek Harness's native runtime continues to manage plugins.

## What to borrow from pi

We reviewed [pi](https://github.com/earendil-works/pi)'s agent core, system prompt and skill loading on 2026-10-08. Its loop separates model requests, tools and events. Context can be transformed at request boundaries; skills advertise names and descriptions before loading full instructions on demand. Team planning is an extension concern rather than a built-in core feature.

For Micro-Multi, the useful principle is to keep the model loop small and enforce collaboration in code. Multi-agent work is our main feature. Dependencies, plan approval and plugin services still need to stay in place.

| Design | Application in Micro-Multi |
| --- | --- |
| Separate requests, tools and UI | Restore the workspace before optional plugin discovery and client loading. |
| Explicit execution state | Wait for the planning turn to finish saving, then check the server revision. Stale or consumed approvals return a conflict instead of starting another planning round. |
| Avoid repeated workflows | Coalesce confirmation calls and tell the lead that approved members are already scheduled. |
| Load detail when needed | Future work could improve plugin tool discovery and member context selection. This update does not change available model tools or dsh dependency resolution. |

Sources: [Agent loop](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts), [system prompt](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/system-prompt.ts), [Skills](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md).

## Enforce collaboration in code

[Open Code Review](https://github.com/alibaba/open-code-review) separates deterministic rules from agent judgment and retrieval. We apply that distinction to collaboration: the model proposes members, files and dependencies; code validates assignments, coordinates paths and consumes approval.

`start_subagents` validates the batch and dependency graph. Independent tasks run within a concurrency limit. Dependent tasks wait for predecessor reports; a failed predecessor stops subsequent writes. `owned_paths`, reservations and path locks coordinate the shared workspace. Repeated dispatch can reuse running or completed execution. The lead collects reports, integrates changes and verifies the result.

These measures reduce duplicate scheduling and accidental starts. They do not guarantee that a team costs less than one agent. Member count, input context, model prices, dependencies and retries all affect cost and completion time. We have not run a shared-task cost benchmark for this update and do not claim a savings percentage.

## Keep dsh compatibility

Cordis Loader, service injection, lifecycle management, native settings forms, ClientModuleSystem, RPC and subscriptions stay in place. Probing a plugin without a client does not boot its Host. Client loading is bounded to three concurrent operations. Builds for one client revision share a lock; different revisions can build concurrently. Native source digests are reused while file metadata remains unchanged.

The changes affect startup and caching. They do not remove required services or prune dependencies by plugin name. Compatibility still depends on a package's entries, dependencies and required services.

The repository already depends on `@deepseek-ai/dsh-llm-pi-ai`. The locked package bridges pi-ai to dsh's LLM interface and describes itself as a DeepSeek adapter. Installing it does not integrate the full pi Agent runtime or all pi model providers. This update keeps the existing execution engines.

## Measurements to make next

Use a fixed model and task set to compare one agent, two members and three members: input/output tokens, first response, completion time, retries and acceptance results. For plugins, separate cold startup, cached builds and packages without clients. Measure when chat becomes usable separately from when all clients finish loading. Use those results to decide whether on-demand tool discovery and smaller member contexts are worthwhile.

See [collaboration](AUTONOMOUS_COLLABORATION.md), [plugin compatibility](NATIVE_CORDIS.md) and [architecture](architecture.md).
