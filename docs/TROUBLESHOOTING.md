# Troubleshooting

Start with the message shown by the app and the tool record for the failed operation. Note which action failed before changing several settings at once.

## A model will not connect

Check that the base URL is an API endpoint rather than a chat website, and that the model ID matches the provider's documentation. Authentication failures usually require checking the key and account access; an unknown-model response requires checking the model ID. For timeouts, check connectivity to the service and the profile's request timeout. Setup steps are in [model configuration](MODELS.md).

If a key cannot be saved on Linux, make sure a Secret Service keyring is running and unlocked. The desktop packages include the application runtimes, but the system keyring is provided by your desktop environment.

## A team has not started

Look for a pending plan card. Team members start only after you confirm the displayed plan. Editing the plan or sending a new task may require another confirmation. Also check for a pending operation approval or a paused conversation. The [team guide](AUTONOMOUS_COLLABORATION.md) describes these stages.

## A plugin is installed but its tools are unavailable

Open its details page and check whether it is enabled and whether configuration is complete. Read any dependency or startup diagnostic. If the plugin uses a CLI or remote service, confirm that the program, account and credentials are available. A plugin that provides only a model or interface component may not add a callable tool.

For a source package, review the build plan if the app asks to build it. An incomplete or failing third-party package needs its reported dependency or build problem addressed before it can run. See [native plugins](NATIVE_CORDIS.md) for the installation flow.

## A task stopped or a test failed

Open the recorded command output or model error. Compare the project files with the conversation before repeating the task. You can continue the conversation with a request to explain the failure or verify the unfinished part. [Recovery](DURABLE_TURNS_AND_MODEL_RECOVERY.md) explains what stopping preserves.

## Desktop or AppImage startup problems

Confirm that the selected port is available and that the data directory is writable. For Linux, check keyring and desktop-library requirements. Ubuntu AppImage launch may need the application-specific namespace policy in the [desktop guide](DESKTOP_RELEASE.md#ubuntu-appimage-sandbox-policy); if FUSE is unavailable, use `--appimage-extract-and-run`.

When reporting a bug, include the app version, OS, action, error text and minimal reproduction steps. Share sanitized logs through [Issues](https://github.com/LKDenchin/Micro-Multi/issues). Vulnerabilities and credentials should go through the private reporting channel in [Security](../SECURITY.md).
