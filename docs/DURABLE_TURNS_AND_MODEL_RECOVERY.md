# Saving and resuming work

Micro-Multi saves conversations and tool events in the local data directory. When you reopen the app, select a conversation from the list to read its messages and continue. Longer conversations may be compacted to keep the working context within the model's limit.

## Pause or stop

Pause an active conversation when you want to inspect its state before continuing. Stop ends the current execution and preserves the content already recorded. Neither action undoes file edits or commands that have finished.

After stopping, read the tool records and inspect the project before giving the next instruction. If a command changed files, started a process or contacted a service, check its actual outcome before asking the agent to repeat it.

## Recover after a failure

A connection failure or truncated reply may leave a task unfinished. Check the error, model connection and output limits, then continue in the same conversation. State which part should resume and whether any work should be verified first. See [troubleshooting](TROUBLESHOOTING.md) for common connection problems.

The desktop records diagnostics when the backend or renderer exits. These logs live in the application data directory. Back up that directory separately from the program, and redact credentials and private content before sharing logs. Storage locations are listed in [deployment](deployment.md).
