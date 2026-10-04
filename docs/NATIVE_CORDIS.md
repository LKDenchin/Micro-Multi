# Native dsh plugins

Micro-Multi supports packages from the deepseek-harness (dsh) ecosystem. A plugin can provide tools to agents, register a model provider or add controls to the app. Client contributions are displayed inside Micro-Multi; you do not need to run a separate dsh WebUI.

## Install and configure a plugin

Open Customization and select Plugins. Read the package description, choose an available source and install it. Sources can be marketplace entries, npm packages, Git repositories or local package directories. A local package needs a `package.json` and supported runtime entries. The agent's `plugin_manager` tool can also manage installation.

Published JavaScript entries load directly. If a source needs building, the application presents a build plan for review, including the local dependencies and build command. Confirm that plan to proceed. Dependencies declared by the package are prepared as part of loading; external CLIs and services follow the plugin's own setup instructions.

Open the installed package's details to configure it. The page uses the plugin's own settings interface, or a form generated from its configuration schema. Save changes and check any validation message. If the plugin provides models, configure its provider and use its model controls where available. A package does not have to supply a tool to be useful.

## Use and manage the package

Enabled tools are available to the lead agent and team members. Interface components appear in the regions the plugin contributes to, while its configuration stays in details. Check the conversation's tool record to see what an agent called.

Disable a package to remove its active contributions, or uninstall it from the installed list. Plugins may use your filesystem, run programs or contact services under your system account. Review the package before installing it and keep its credentials private.

## Develop a local plugin

Start with [examples/native-cordis](../examples/native-cordis). A package can use a standard runtime export, or declare a local entry and configuration in `microMulti.cordis`. Several entries can be declared together:

```json
{
  "name": "my-dsh-plugin",
  "type": "module",
  "microMulti": {
    "cordis": {
      "plugins": [
        {"entry": "counter.mjs", "config": {"start": 10}},
        {"entry": "tool.mjs"}
      ]
    }
  }
}
```

Keep entries within the package and declare their dependencies. Host services include `tools`, `systemPrompt` and `microMulti`; `microMulti.workspace` and `microMulti.pluginRoot` identify the workspace and source locations. Use native Cordis APIs for service injection, events and resource disposal. Tool arguments and results follow the official dsh tool runtime.

Client packages declare their entries and dependencies through dsh metadata. Their modules use the official client module system and shared renderer. Source-mode hosting requires Node.js 24+; desktop packages supply it. `MICRO_MULTI_NODE` can select another runtime.

See [architecture](architecture.md), [runtime interfaces](contracts.md) and [upstream provenance](UPSTREAM_RUNTIME_PROVENANCE.md) for implementation references. The upstream framework is [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness).
