# Projects and conversations

A project connects a conversation to a local folder. Agents operate on that folder, and the workspace inspector lets you read the files and examine their changes. You can also start a conversation without a project for questions that do not need local files.

## Open a project

Add a local project, enter its name and choose the folder. With Link this directory selected, file edits affect the original directory. A directory without Git is initialized as a repository. Check the chosen path before confirming, especially when working with an existing project.

Select the project when starting a conversation. The file tree shows its contents; open a file to read it, and use the Changes or Review view to inspect Git diffs. Keep the project's usual build tools and dependencies installed so commands can run in that directory.

## Start and continue a conversation

Choose the model, mode and permissions in the composer, then write the task. Include the files or behavior involved, any constraints and how you expect it to be checked. For example, explain which response fields must remain unchanged or which tests should be run.

Use the attachment control to add supporting files. The + menu lists enabled tools and other capabilities. Replies, tool calls and team reports stay with the conversation, so you can reopen it from the list and send a follow-up without starting over.

## Inspect the work

A reply describes what the agent did; the files and tool records show the result. Read the diff for a code change and check the command output for validation. A reported test failure may come from the change, the environment or an existing problem, so use the recorded output to decide what to do next.

The right-hand inspector brings together files, diffs, reviews, previews and terminal activity. In team mode, the team view adds each member's task and status. You can pause or stop an active conversation; completed operations remain on disk. See [history](replay.md) and [recovery](DURABLE_TURNS_AND_MODEL_RECOVERY.md) before repeating work after an interruption.
