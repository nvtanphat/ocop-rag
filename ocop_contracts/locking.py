"""Process-owned filesystem locks; the OS releases locks after a hard stop."""
from contextlib import contextmanager
import json
import os
from pathlib import Path


@contextmanager
def process_lock(path: Path):
    """Nonblocking cross-platform lock with PID metadata; stale PID is harmless.

    Keep the inode/path after release: deleting a lock file permits concurrent
    processes to lock different inodes with the same name.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b" ")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(f"another process owns lock: {path}") from exc
        try:
            stream.seek(0)
            stream.truncate()
            stream.write(json.dumps({"pid": os.getpid()}).encode())
            stream.flush()
            os.fsync(stream.fileno())
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
