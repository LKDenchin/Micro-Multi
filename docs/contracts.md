# Runtime interfaces

The local HTTP service exposes health, projects, conversations, model profiles, workspace files, extensions, and task controls. The web client consumes structured responses and streamed task events.

Tools declare a name, description, and parameter schema. Calls are checked against the schema and permission policy before execution. dsh Cordis tools use the official tool runtime for validation and structured output.

Keep interface changes compatible with the desktop client and update behavior tests when changing request, response, or event semantics.
