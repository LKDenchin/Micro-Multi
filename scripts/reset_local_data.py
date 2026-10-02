"""Erase only this checkout's application data and publication evidence."""

from __future__ import annotations

import argparse
import shutil
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (".masp", "evidence", ".research", "docs/screenshots")


def remove_readonly(function: object, path: str, error: BaseException) -> None:
    if not isinstance(error, PermissionError):
        raise error
    candidate = Path(path).resolve()
    if not candidate.is_relative_to(ROOT):
        raise ValueError("Refusing to change permissions outside checkout")
    candidate.chmod(stat.S_IWRITE | stat.S_IREAD)
    # Windows attachments and Git object files can intentionally be read-only.
    if callable(function):
        function(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Delete the listed data")
    args = parser.parse_args()
    paths = [(ROOT / name).resolve() for name in TARGETS]
    for path in paths:
        if not path.is_relative_to(ROOT) or path == ROOT:
            raise SystemExit(f"Unsafe reset path: {path}")
        print(f"{'DELETE' if args.execute else 'PREVIEW'} {path}")
    if not args.execute:
        return
    # Delete service-scoped credentials, including orphaned/deleted model profiles.
    # Never print credentials or credential blobs.
    if sys.platform == "win32":
        import pywintypes
        import win32cred

        try:
            credentials = win32cred.CredEnumerate(None, 0)
        except pywintypes.error as error:
            if error.winerror != 1168:
                raise
            credentials = []
        homes = [str(path).lower() + "::" for path in paths]
        removed = 0
        for credential in credentials:
            target = credential["TargetName"]
            username = credential.get("UserName", "").lower()
            belongs = target == "masp-workspace" or target.endswith("@masp-workspace")
            if belongs and any(username.startswith(home) for home in homes):
                win32cred.CredDelete(target, credential["Type"], 0)
                removed += 1
        print(f"Removed {removed} application credential entries")
    else:
        # This cleanup tool intentionally targets this checkout, not arbitrary homes.
        import json
        import sqlite3

        import keyring
        from keyring.errors import PasswordDeleteError

        for home in paths:
            database = home / "store.sqlite3"
            if not database.exists():
                continue
            with sqlite3.connect(database) as connection:
                rows = connection.execute(
                    "SELECT data FROM records WHERE kind='model_profile'"
                ).fetchall()
            for (record,) in rows:
                profile = json.loads(record)
                try:
                    keyring.delete_password("masp-workspace", f"{home}::{profile['id']}")
                except PasswordDeleteError:
                    pass
    for path in paths:
        if path.exists():
            shutil.rmtree(path, onexc=remove_readonly)
    print("Application data erased. The next launch creates a fresh workspace.")


if __name__ == "__main__":
    main()
