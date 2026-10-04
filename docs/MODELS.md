# Connecting a model

Micro-Multi uses the model service you configure. Before starting a conversation, obtain the service's API base URL, model ID and credentials. The endpoint must support the application's OpenAI-compatible chat requests; a service's display name alone does not establish compatibility.

## Add and test a connection

Open Settings, choose Models, then Add or edit model. Give the connection a name you will recognize in the composer. Enter the base URL supplied by the service, the exact model ID and the API key. For a service that documents a base such as `https://api.example.com/v1`, enter that base rather than a web chat address.

Save the profile and test the connection. If the test fails, check the returned message before changing settings: an authentication error, an unknown model and an unreachable server need different fixes. The [troubleshooting guide](TROUBLESHOOTING.md) covers these cases.

## Choose a model for the task

Select a saved profile in the conversation composer. The name identifies your local configuration; the model ID is what the remote API receives. This lets you keep several connections to the same service or use different services for different tasks.

In team mode, members follow the lead model by default. You can choose another model for a member in the team editor before confirming the plan. Pick a model that supports the tools the member needs. Plugin-provided models may require additional configuration in that plugin's details page.

## Request settings and credentials

The model form also exposes temperature, top-p, maximum output tokens and request timeout. Use settings supported by your provider. An output limit controls the reply length; it does not set the model's full context window. If a task is cut short, inspect the response and limit before raising it.

Profile API keys are stored in the OS credential store rather than the project's files. On Linux this requires a running, unlocked Secret Service keyring. You can also configure an environment-based model through `MASP_MODEL_BASE_URL`, `MASP_MODEL_NAME` and `MASP_MODEL_API_KEY` in source deployments; see [deployment](deployment.md).
