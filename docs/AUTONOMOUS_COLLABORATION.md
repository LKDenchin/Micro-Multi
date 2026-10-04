# Reviewed team collaboration

Select multi-agent collaboration in the composer and describe the outcome, constraints and acceptance criteria. The lead first analyses the request, reads relevant materials and writes requirement, design and task documents, then submits a complete team plan. Preparation permits analysis and planning documents; members do not start during this phase.

## Review and execute

The collaboration card shows the pending plan. Edit responsibilities, prompts, file ownership and models with Adjust team. Confirm execution starts only that plan version. A new task or feedback creates a new version; prior approval is not reused. Approval is consumed once and stale cards cannot launch work. Plan records live in `.masp/team-plans/`; conversation history retains the cards.

Members initially follow the lead model. Explicit model choices made in the team editor are preserved in execution. Model-generated member creation or scheduling cannot silently replace these choices. Saving the team synchronizes the lead model and composer selection.

## Follow, interrupt and recover

The team view shows status, tasks and reports. Tool records show files, commands, extension calls and approvals. Add guidance during work, or pause/stop execution. The lead can use `remove_subagent` to cancel a failed member; cancellation completes and file reservations are released before another approach starts.

Repeated scheduling of the same member/task within a turn shares its existing execution or completed report. New tasks execute normally and failed work can be retried. Acceptance criteria remain for the lead to verify; a reused report is not evidence that a new check ran.

Configure model endpoints in Models and plugins, Skills and MCP in Customization. The composer + menu lists enabled capabilities. Native plugin tools are available to the lead and members. Inspect diffs, verification and reports before accepting the outcome; continue in the same saved conversation. See [models and recovery](DURABLE_TURNS_AND_MODEL_RECOVERY.md) and [native plugins](NATIVE_CORDIS.md).
