# Conversations, streaming and model recovery

Projects, conversations, tool events and streamed replies are stored in the local data directory. Reopen a saved conversation to continue work. Context compaction retains task information and loop-detection state for longer sessions.

Stream events are coalesced while preserving semantic boundaries and final status. Batched persistence, incremental replay, scheduled Markdown rendering and merged directory refreshes reduce repeated work. SQLite retains WAL and full synchronization. MCP discovery is cached, connections are reused, and cancellation cleans up active calls.

Compatible model requests accept SSE or JSON replies, text content blocks, reasoning fields and structured tool arguments. When a provider explicitly rejects an optional parameter before generation with HTTP 400/422, bounded negotiation removes that optional parameter or renames the token limit when the provider identifies the replacement. Messages, tools, model selection and authentication remain mandatory. Negotiation is cached per endpoint/model.

Stopping preserves recorded content. Network failures and truncation retain their actual cause; unfinished output is not marked as successful. Check endpoint, network and credentials, then continue the existing conversation. Inspect files and tool records before repeating operations with side effects.

The desktop monitors backend exits and renderer state, records diagnostics and restores the workspace. Logs are in the application data directory; redact secrets before sharing. See [deployment](deployment.md) for storage paths and [current changes](CURRENT_CHANGES.md) for this source update.
