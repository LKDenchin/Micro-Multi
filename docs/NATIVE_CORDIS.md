# Native dsh plugins

Micro-Multi runs published deepseek-harness plugins through the official Cordis Loader and ClientModuleSystem. Cordis 4.0.4 and the locked dsh 0.2.0-rc.1 runtime form the host SDK. Host tools are available to both the lead agent and team members. Micro-Multi mounts client contributions inside its own interface; it does not start a separate dsh WebUI.

## Install and build

Open Customization, select a marketplace package, npm package, Git source or local directory, and review its source and requested access. The agent can also use `plugin_manager` to install an extension. Sources require a `package.json` and a supported host or client entry. Try [examples/native-cordis](../examples/native-cordis).

Published JavaScript artifacts are loaded directly. A runtime activation error does not by itself trigger a rebuild. If artifacts need building, the reviewed build plan includes package-local development and optional dependencies before the build command, so tools such as Vite are available even when the surrounding npm environment omits development dependencies. Installing dependencies does not execute their lifecycle scripts; source builds remain subject to the application's existing approval flow.

The generic resolver reads npm dependencies, peer/dev declarations and `dsh.client.inject` metadata. Missing declared libraries go into an application-owned dependency cache. Package metadata remains discoverable when `package.json` is hidden by exports. Framework packages use the host SDK version or a compatible published version no newer than the host. Ordinary plugin dependencies retain their package declarations.

## Entries and service injection

Single local entries can use `microMulti.cordis.entry` and `config`. Multiple entries can declare:

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

Entries stay inside the package root. ESM/CJS exports, configuration validation and native Loader entry IDs are preserved. Bundle entry options, isolation, interception, disabled state and expressions follow the native Loader lifecycle.

The host resolves required services recursively from the official dsh base composition and provider metadata. This includes `timer`, `sessionQuery`, `workspaceRegistry` and configured storage backends. Providers activate on demand; the host does not eagerly execute an entire plugin catalogue. Missing real providers and startup errors produce a concrete diagnostic and roll back failed activation.

The application provides `tools`, `systemPrompt` and `microMulti`; `microMulti.workspace` and `microMulti.pluginRoot` expose the corresponding paths. Tools use the official dsh parameter validation and structured output. Register services, events and effects with native Cordis APIs. Disable, reinstall, removal and normal shutdown dispose resources.

## Settings and client pages

A plugin's own settings contributions appear in its details page. A declared Config schema can generate an editable form when the plugin has no custom settings page. Forms use native settings remotes, support ordinary fields and JSON for complex values, and preserve secret-field behavior. Validation and complete lifecycle restart succeed before atomic persistence; failed changes restore the prior configuration.

Legacy namespace settings use the original published SettingsProvider, supporting `get`, `register`, watch/update/mutate and revision conflicts alongside the current Config forms. Previous saved namespace values are migrated on read. See [runtime provenance](UPSTREAM_RUNTIME_PROVENANCE.md).

Client factories, synchronous and asynchronous requires, chunk registration and caches use ClientModuleSystem. Dependency and child-slot discovery uses JavaScript syntax analysis. Native parent components own their declared child slots. Settings slots and body portals are contained in plugin details; conversation and explicit shell contributions are mounted in their respective application regions. Native locale and renderer services provide the actual client interfaces.

Browser bundles disable Node-internal probes instead of relying on a browser `process` global. Client JS/CSS and host reuse incorporate runtime source and lock-file revisions, invalidating stale assets after upgrades. Persistent plugin subscriptions use WebSocket so they do not exhaust the browser HTTP connection pool. Native HTTP routes preserve streaming, binary bodies and response headers.

## Runtime, permissions and diagnostics

Package/workspace hosts are separate Node processes with bounded startup/call time and logs. A terminated host is recreated on a later explicit call. Data and dependency caches belong to Micro-Multi, independently of an external dsh installation. Source operation needs Node.js 24+; desktop packages supply Node. `MICRO_MULTI_NODE` can select another runtime.

Plugins run with the current user's system permissions. Process separation and integrity-verified framework source snapshots protect host stability; they are not an OS sandbox for arbitrary plugin code. External CLIs, account login, provider credentials and network services still require their own setup. Do not treat successful installation as verification of every remote provider operation.

See [extensions](extensions.md), [current changes](CURRENT_CHANGES.md) and [security](../SECURITY.md). Framework reference: [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness).
