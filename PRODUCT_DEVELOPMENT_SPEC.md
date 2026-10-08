# Multi-agent task examples

The following examples show how to describe work in Micro-Multi. Replace the paths, test commands and constraints with those from your project.

## Investigate a project in parallel

Open the project, choose team mode and ask-for-approval permissions:

```text
Split investigation into request entry points, database access and test structure.
Each member reads its assigned scope and cites actual files. The lead combines
the call flow and open questions. Do not change code.
```

Use the file browser to follow the references. If you need more detail, ask about one module in the same conversation.

## Make a focused change

For a small bug or feature, specify both the behavior and the check:

```text
Fix the empty-list error in the search endpoint. Preserve the existing
response shape, add a regression test and run the endpoint tests.
```

Use the lead alone for this short task. Choose permissions that allow the required edits and commands, then inspect the diff and test output.

## Split implementation and testing

Choose team mode for a change that can be divided into roles:

```text
Add pagination to the order API. One member should implement the endpoint,
another should cover boundary cases, and the lead should review the diff.
Keep the existing fields and document the page parameters.
```

Review the team, files and models before confirming. Independent work can run concurrently; integration tests that need the changed endpoint should depend on its implementation. Inspect the endpoint, tests and documentation together. See [team collaboration](docs/AUTONOMOUS_COLLABORATION.md).

## Handle successive stages in one file

```text
Have the API member update api.py, then have the validation member check
error handling and run endpoint tests. Both tasks own api.py, but validation
depends on implementation. If implementation fails, stop further edits
and have the lead explain the failure.
```

The two stages share a file and need an explicit dependency, rather than concurrent writes.

## Give members dsh plugin tools

```text
Use the enabled DeepSeek Harness tools to inspect the project. Split code
and documentation checks between members. The lead combines tool results
and issues. Keep existing plugin configuration; do not reinstall plugins
or start an external agent to repeat the entire job.
```

The lead and members can use the same enabled toolset. See [native plugins](docs/NATIVE_CORDIS.md) for installation, configuration and compatibility.

## Repeat a project workflow

If you regularly ask for the same checks, put the requirements in a project Skill under `.agents/skills/`. For tools outside the project, configure an MCP connection or plugin in Customization and complete its setup. Then name the relevant workflow or capability in your task. See [extensions](docs/extensions.md).
