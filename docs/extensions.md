# Extensions

Skills provide reusable instructions in `SKILL.md` files. Store project Skills in `.agents/skills/` or add user Skills through the workspace. MCP servers expose tools through configured connections. Local command plugins connect command-based tools.

Micro-Multi also supports the deepseek-harness (dsh) Cordis Host plugin ecosystem. See the [dsh plugin guide](NATIVE_CORDIS.md) for package entries, configuration, services, lifecycle, and execution permissions.

Manage extensions from Customization (some entries are available through Settings). Review the code and requested access before loading a package, and use the workspace permissions to control operations.

Source builds retain the reviewed build flow. External CLIs, accounts and credentials follow the plugin setup instructions; the composer + menu lists enabled capabilities.
