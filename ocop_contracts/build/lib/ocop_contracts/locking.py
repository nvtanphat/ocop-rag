"""Process-owned filesystem locks; the OS releases locks after a hard stop."""
from contextlib import contextmanager
import json
import os
import time
from pathlib import Path


@contextmanager
def process_lock(path: Path, *, wait_timeout: float = 0):
    """Nonblocking cross-platform lock with PID metadata; stale PID is harmless.

    Keep the inode/path after release: deleting a lock file permits concurrent
    processes to lock different inodes with the same name.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR, 0o600), "r+b") as stream:
        deadline=time.monotonic()+wait_timeout
        while True:
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic()>=deadline:
                    raise RuntimeError(f"another process owns lock: {path}") from exc
                time.sleep(.05)
        try:
            stream.seek(0)
            stream.write(json.dumps({"pid": os.getpid()}).encode())
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
