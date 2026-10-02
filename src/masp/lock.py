"""OS-released exclusive ownership of a local scheduler data directory."""

import sys
from pathlib import Path


class InstanceLock:
    def __init__(self, path: Path):
        self.stream = path.open("a+b")
        self.stream.seek(0)
        if path.stat().st_size == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise ValueError("Another Micro-Multi service owns this data directory") from None

    def close(self) -> None:
        self.stream.close()
