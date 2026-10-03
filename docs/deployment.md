# Deployment

Use the desktop installer for Windows or the Debian / AppImage package for Linux. See the [desktop build guide](DESKTOP_RELEASE.md) for reproducible builds and package verification.

For source operation, install Python 3.11+, Node.js 24+, Git, Python dependencies, and locked npm dependencies. Run `python -m masp.cli serve` and open `http://127.0.0.1:3080/`. Keep the service bound to the local machine.

Use `MASP_HOME` for a dedicated writable data directory. Configure model credentials through the workspace and operating system credential store. Back up local data separately from application files.
