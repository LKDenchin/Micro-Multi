# Adding instructions and tools

Extensions let you give agents task-specific instructions or connect tools outside the built-in workspace. Open Customization to manage plugins, Skills and MCP servers. Choose the extension type based on what you want to add.

## Skills: reusable instructions

A Skill is a `SKILL.md` file describing how to perform a task. Use one for project conventions, a review checklist or a workflow you repeat. Store project Skills in `.agents/skills/`, or add a user Skill through Customization. Instructions should describe when the Skill applies and what a finished result requires.

## MCP: connect a service's tools

An MCP connection exposes tools from a local or remote server. Configure the server address or startup command and any credentials it needs, then check that the connection is available. Local servers need their runtime and dependencies installed; remote servers need a reachable endpoint. Only enable the tools you intend to use for the task.

## Plugins: add capabilities to the app

The plugin page includes a catalogue and installed packages. Open a package to read its description, install it, then use its details page to configure parameters. A dsh plugin may add tools, model providers or controls in the conversation interface. A local command plugin exposes tools implemented by a command.

Some plugins require an external program, an account or their own API key. Complete that setup before asking the agent to use them. Disabling a plugin removes its active contributions; removing it uninstalls the package. The [dsh guide](NATIVE_CORDIS.md) explains supported sources and plugin development.

## Use an extension in a conversation

The composer's + menu lists enabled capabilities. Describe when the agent should use a tool or Skill, and inspect the resulting tool calls in the conversation. Tools supplied by native plugins can be used by the lead agent and team members.

Review the source and access requirements before enabling an extension. Local programs and native plugins run under your user account, and external services may receive task data. See [permissions](sandbox.md) for the application's operation controls.
