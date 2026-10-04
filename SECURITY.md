# Security policy

Micro-Multi is a single-user loopback application. Keep its API on the local machine. Security fixes are provided for the latest published version.

## Trust boundaries

- Model services receive conversation context and selected tool results.
- Profile keys use the OS credential store. Extension configuration and logs may contain sensitive values; redact before sharing.
- Local commands run on the host. Permission checks do not provide an OS sandbox.
- Optional Docker verification refuses host fallback; it does not isolate all chat tools or extensions.
- Skills, MCP servers, native packages, and plugins are trusted inputs. Review their source and requested access.
- Uninstall preserves data. See the README for erasure instructions.

## Reporting

Use [Security → Report a vulnerability](https://github.com/LKDenchin/Micro-Multi/security/advisories/new) to send a private vulnerability report. Never post credentials, exploit details or unredacted logs in public issues.

Include affected versions, reproduction steps, impact, and a minimal sanitized example. No response time or bug bounty is currently guaranteed.
