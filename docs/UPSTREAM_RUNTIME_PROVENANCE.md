# Upstream runtime provenance

Micro-Multi imports the following published runtime packages directly. These are upstream implementations, not original Micro-Multi code. Installation metadata and package-lock.json identify the concrete artifacts. Their distributed LICENSE files must remain with the packages.

| Package | Installed version | Declared license |
|---|---|---|
| `@deepseek-ai/cordis` | `4.0.4` | MIT |
| `@deepseek-ai/dsh-agent` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-agent-loop` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-app-boot` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-fs-local` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-llm` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-llm-pi-ai` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-session` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-session-persistence-jsonl` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-session-projection` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-skill` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-skill-filesystem` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-subagent` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-subagent-fork-in-process` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-subagent-spawn-in-process` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-system-prompt` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-tools` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-attachment` / `dsh-attachment-local` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-llm-deepseek` / `dsh-anonymous-user-id` | `0.2.0-rc.1` | MIT |
| `@deepseek-ai/dsh-user-approval` | `0.2.0-rc.1` | MIT |

Harness package repository: https://github.com/deepseek-ai/deepseek-harness. Local source review checkout: 4878cdabd87d4041bdaff61d04c966883b9fd07a; this is not a claim that every npm artifact was published from that commit.

Representative license copies are retained in docs/licenses/HARNESS_MIT_LICENSE.txt and docs/licenses/CORDIS_LICENSE.txt. Each installed package remains the authoritative source for its complete notice.

Adapted component sources retain their original licenses and origin records alongside the source files. See NOTICE for redistribution notices. Application orchestration, transport adapters, configuration forms and desktop UI are maintained in this repository.


## Native plugin compatibility sources

The original `@deepseek-ai/dsh-settings@0.0.1-rc.3` namespace SettingsProvider is retained unchanged in `src/masp/native/vendor/dsh-settings-namespace/index.mjs`. Its LICENSE and provenance.json record the published archive URL and SHA-256. This isolated service coexists with the current Config settings implementation; the adapter and persistence layer are Micro-Multi code.

Framework snapshots are extracted from published npm archives verified against package-lock.json integrity and checked per source file. The snapshot identity uses framework versions, sources and integrity, rather than unrelated lock-file changes. Host loading and client bundling read this baseline; a plugin's modification of installed SDK sources is not accepted as a new baseline. Complete current versions are recorded in [package.json](../package.json) and [package-lock.json](../package-lock.json).
