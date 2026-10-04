# Working with a team

Team mode is useful when a task has distinct responsibilities, such as implementation, tests and review. The lead agent prepares the plan and coordinates the members. You decide whether that plan should run.

## Review the plan

Choose multi-agent collaboration in the composer and describe the task, constraints and acceptance criteria. During preparation, the lead reads relevant material and writes requirement, design and task documents. Members do not start until you confirm the plan.

The plan card lists the proposed team. Open Adjust team to edit roles, prompts, assigned files and models. Check that the responsibilities fit the task and that members are not making conflicting changes to the same files. Then choose Confirm execution to start the displayed version. A new task or round of feedback produces another plan and needs another confirmation.

## Follow execution

Members follow the lead model unless you select a different one. Their assignments, status and reports appear in the team view. Tool records show file operations, commands and extension calls, including any approvals.

You can send additional instructions while the team works. Pause the conversation when you need to inspect the current state, or stop it to end execution. The lead can remove a failed member before trying another approach; removal cancels that member's work and releases its file reservations.

## Check the result

After the members report back, inspect the resulting files, diffs and validation output. A member's completion report is not a substitute for a successful test or review. If something is missing, explain it in a follow-up and review the next plan.

Plan records are stored in `.masp/team-plans/` within the workspace, and plan cards remain in the conversation history. For an example task with implementation and test roles, see [task examples](../PRODUCT_DEVELOPMENT_SPEC.md).
