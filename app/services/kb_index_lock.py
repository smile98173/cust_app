from contextlib import contextmanager
from pathlib import Path
import threading
import time
from typing import Iterator, Union

from filelock import FileLock


_ACTIVE_INDEX_OPERATIONS = 0
_ACTIVE_INDEX_OPERATIONS_CONDITION = threading.Condition()


def active_index_operation_count() -> int:
    with _ACTIVE_INDEX_OPERATIONS_CONDITION:
        return _ACTIVE_INDEX_OPERATIONS


def wait_for_no_active_index_operations(timeout_seconds: float) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds or 0))
    with _ACTIVE_INDEX_OPERATIONS_CONDITION:
        while _ACTIVE_INDEX_OPERATIONS > 0:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            _ACTIVE_INDEX_OPERATIONS_CONDITION.wait(timeout=remaining)
        return True


@contextmanager
def interprocess_index_lock(
    lock_path: Union[str, Path],
    *,
    timeout_seconds: float = 1800,
) -> Iterator[None]:
    """Serialize Chroma mutations across backend processes."""
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path), timeout=timeout_seconds)
    with lock:
        global _ACTIVE_INDEX_OPERATIONS
        with _ACTIVE_INDEX_OPERATIONS_CONDITION:
            _ACTIVE_INDEX_OPERATIONS += 1
            _ACTIVE_INDEX_OPERATIONS_CONDITION.notify_all()
        try:
            yield
        finally:
            with _ACTIVE_INDEX_OPERATIONS_CONDITION:
                _ACTIVE_INDEX_OPERATIONS = max(0, _ACTIVE_INDEX_OPERATIONS - 1)
                _ACTIVE_INDEX_OPERATIONS_CONDITION.notify_all()
