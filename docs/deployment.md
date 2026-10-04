# Run from source

Source mode is useful for development or for running the interface in a browser. Prepare Python 3.11+, Node.js 24+, npm and Git, then work from the repository root. For a desktop package, use the [installation guide](DESKTOP_RELEASE.md) instead.

## Install and start

Create a Python environment:

```bash
python -m venv .venv
```

Activate it with `.\.venv\Scripts\Activate.ps1` in Windows PowerShell, or `source .venv/bin/activate` on Linux. Install the Python package and locked JavaScript dependencies:

```bash
python -m pip install -e ".[dev]"
npm ci
```

Run `npm run desktop` for the Electron app. To use the browser interface, run `python -m masp.cli serve` and open `http://127.0.0.1:3080/`. Keep the service on the local machine; it is a single-user application.

## Configuration

| Variable | Purpose |
| --- | --- |
| `MASP_HOME` | Select a writable application data directory. Source mode defaults to `.masp` in the working directory. |
| `MASP_PORT` | Choose the desktop backend port, which defaults to `3080`. |
| `MASP_MODEL_BASE_URL` | Provide an environment-based model endpoint. |
| `MASP_MODEL_NAME` | Specify that model's ID. |
| `MASP_MODEL_API_KEY` | Supply its credential; keep it out of repository files. |
| `MICRO_MULTI_NODE` | Select a Node runtime for native hosting. |

Model profiles added through the interface store their keys in the OS credential store. Use [model configuration](MODELS.md) for that flow. Extensions may require their own runtime, account or environment settings.

## Data and backups

Installed desktop data defaults to `%APPDATA%\Micro-Multi\data` on Windows and `${XDG_CONFIG_HOME:-~/.config}/Micro-Multi/data` on Linux. `MASP_HOME` can override the path. Application updates and uninstall preserve this data.

Back up the data directory separately from the program, preferably after stopping active work. Model credentials live in the OS store, so a copied data directory is not a backup of those keys. Projects linked to their original folders also need their own backups. See [architecture](architecture.md) for the storage layout and [recovery](DURABLE_TURNS_AND_MODEL_RECOVERY.md) for interrupted tasks.
