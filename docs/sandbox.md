# Permissions and execution

Select the appropriate permissions in the conversation before running agent work. Read, file, and command operations use the workspace's approval policy. Review requested commands and file changes when prompted.

The Electron renderer uses context isolation and Chromium sandboxing. Native dsh plugins execute as local Node processes with the current user's system permissions; process isolation contains failures. Install trusted plugins and inspect their code.

Docker-based execution requires a separately installed Docker environment. Keep private credentials outside project files and remove sensitive content from shared logs.
