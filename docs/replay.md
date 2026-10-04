# Reviewing conversation history

Open a saved conversation to read replies, tool calls, operation approvals and member reports. These records help you understand what has already happened before continuing a task.

For a file change, compare the current contents and Git diff with the agent's explanation. For a command, read its arguments, exit status and output. For team work, check the member reports alongside the files and validation they refer to.

An interrupted task may still have completed some operations. Before asking the agent to repeat them, check for existing files, running processes or remote changes. Continue with a message that identifies the missing work, such as “The tests passed, but the API documentation is still missing; add that next.”

Conversation records are local application data. They may contain project content and tool output, so redact private material before sharing them. See [saving and recovery](DURABLE_TURNS_AND_MODEL_RECOVERY.md) and [data storage](deployment.md).
