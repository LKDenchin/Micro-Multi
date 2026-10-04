# Task examples

The following examples show how to describe work in Micro-Multi. Replace the paths, test commands and constraints with those from your project.

## Understand an unfamiliar project

Open the project, choose the lead agent and ask-for-approval permissions, then ask:

```text
Trace how a request reaches the order service. Identify the entry point,
the validation code and the database calls. Explain the flow using the
actual files, without changing them.
```

Use the file browser to follow the references. If you need more detail, ask about one module in the same conversation.

## Make a focused change

For a small bug or feature, specify both the behavior and the check:

```text
Fix the empty-list error in the search endpoint. Preserve the existing
response shape, add a regression test and run the endpoint tests.
```

Choose permissions that allow the required edits and commands. Read the diff and test output after execution. A failed test should be explained before you accept the change.

## Split implementation and testing

Choose team mode for a change that can be divided into roles:

```text
Add pagination to the order API. One member should implement the endpoint,
another should cover boundary cases, and the lead should review the diff.
Keep the existing fields and document the page parameters.
```

Review the proposed team, assigned files and models before confirming. Once it finishes, inspect the endpoint, tests and documentation together. See [team collaboration](docs/AUTONOMOUS_COLLABORATION.md).

## Repeat a project workflow

If you regularly ask for the same checks, put the requirements in a project Skill under `.agents/skills/`. For tools outside the project, configure an MCP connection or plugin in Customization and complete its setup. Then name the relevant workflow or capability in your task. See [extensions](docs/extensions.md).
