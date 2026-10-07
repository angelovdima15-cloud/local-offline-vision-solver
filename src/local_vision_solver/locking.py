from contextlib import contextmanager
from pathlib import Path
import os


@contextmanager
def file_lock(path: Path):
    """OS releases the lock after a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another session is using this model. Wait until it finishes.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def inference_lock(endpoint):
    # Path compatibility is limited to source tests; product callers use the endpoint.
    if isinstance(endpoint, Path):
        return file_lock(endpoint / ".inference.lock")
    from .runtime_lock import runtime_lock
    return runtime_lock(endpoint)
