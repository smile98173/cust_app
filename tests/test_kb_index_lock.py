import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.kb_index_lock import (
    active_index_operation_count,
    interprocess_index_lock,
    wait_for_no_active_index_operations,
)


def test_interprocess_index_lock_tracks_active_operations_until_release():
    with TemporaryDirectory() as tmp:
        lock_path = Path(tmp) / "test-index-lock.lock"
        entered = threading.Event()
        release = threading.Event()

        def worker():
            with interprocess_index_lock(lock_path, timeout_seconds=5):
                entered.set()
                release.wait(timeout=5)

        thread = threading.Thread(target=worker)
        thread.start()
        assert entered.wait(timeout=5)
        assert active_index_operation_count() == 1
        assert wait_for_no_active_index_operations(0.01) is False

        release.set()
        thread.join(timeout=5)

        assert not thread.is_alive()
        assert wait_for_no_active_index_operations(1) is True
        assert active_index_operation_count() == 0
