"""Release must survive short Windows sharing conflicts without hiding lock leaks."""
import errno
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.test_gt import SCRIPTS  # noqa: F401 - makes the packaged runtime importable
from goalteams import util


def sharing_error(code=32):
    error = PermissionError(errno.EACCES, "the file is in use by another process")
    error.winerror = code
    return error


class FileLockReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gt-filelock-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / ".lock"

    def assert_closed(self, lock, fd):
        self.assertIsNone(lock._fd)
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_transient_windows_sharing_and_lock_violations_release_and_allow_reacquisition(self):
        for code in (32, 33):
            with self.subTest(winerror=code):
                self.path = self.path.with_name(".lock-%d" % code)
                remove = os.remove
                attempts = []

                def temporarily_busy(path):
                    attempts.append(path)
                    if len(attempts) <= 2:
                        raise sharing_error(code)
                    return remove(path)

                lock = util.FileLock(self.path)
                self.assertEqual(lock.timeout, 20.0)
                with mock.patch.object(util.os, "remove", side_effect=temporarily_busy):
                    with lock:
                        fd = lock._fd
                self.assert_closed(lock, fd)
                self.assertFalse(self.path.exists(), "release must not silently leave a live-owner lock")
                self.assertEqual(len(attempts), 3)
                with util.FileLock(self.path):
                    self.assertTrue(self.path.exists())
                self.assertFalse(self.path.exists())

    def test_permanent_permission_error_is_reported_without_retry_and_fd_is_closed(self):
        lock = util.FileLock(self.path)
        with mock.patch.object(util.os, "remove", side_effect=PermissionError(errno.EACCES, "denied")) as remove:
            with self.assertRaises(util.GTError) as caught:
                with lock:
                    fd = lock._fd
        self.assert_closed(lock, fd)
        self.assertEqual(remove.call_count, 1)
        self.assertIn(str(self.path), str(caught.exception))
        self.assertTrue(self.path.exists(), "a failed release must remain visible for diagnosis")

    def test_persistent_windows_sharing_failure_is_bounded_and_reported(self):
        lock = util.FileLock(self.path)
        started = time.monotonic()
        with mock.patch.object(util.os, "remove", side_effect=sharing_error()) as remove:
            with self.assertRaises(util.GTError):
                with lock:
                    fd = lock._fd
        elapsed = time.monotonic() - started
        self.assert_closed(lock, fd)
        self.assertGreater(remove.call_count, 1)
        self.assertLessEqual(remove.call_count, 25, "cleanup retries must have a finite budget")
        self.assertLess(elapsed, 5, "release must not consume another acquire timeout")
        self.assertTrue(self.path.exists())

    def test_retry_does_not_unlink_a_replacement_lock(self):
        replacement = self.path.with_name("replacement")
        replacement.write_text("another owner\n", encoding="ascii")
        replacement_identity = replacement.stat().st_ino
        lock = util.FileLock(self.path)

        def replace_then_conflict(path):
            os.replace(replacement, path)
            raise sharing_error()

        with mock.patch.object(util.os, "remove", side_effect=replace_then_conflict) as remove:
            with self.assertRaises(util.GTError):
                with lock:
                    fd = lock._fd
                    self.assertNotEqual(os.fstat(fd).st_ino, replacement_identity)
        self.assert_closed(lock, fd)
        self.assertEqual(remove.call_count, 1, "do not issue another unlink against a different owner")
        self.assertEqual(self.path.read_text(encoding="ascii"), "another owner\n")

    def test_successful_cleanup_preserves_the_body_exception(self):
        remove = os.remove
        calls = []

        def temporarily_busy(path):
            calls.append(path)
            if len(calls) == 1:
                raise sharing_error()
            return remove(path)

        lock = util.FileLock(self.path)
        with mock.patch.object(util.os, "remove", side_effect=temporarily_busy):
            with self.assertRaisesRegex(ValueError, "body failed"):
                with lock:
                    fd = lock._fd
                    raise ValueError("body failed")
        self.assert_closed(lock, fd)
        self.assertFalse(self.path.exists())

    def test_already_absent_lock_is_released_and_fd_is_closed(self):
        lock = util.FileLock(self.path)
        remove = os.remove

        def remove_then_report_missing(path):
            remove(path)
            raise FileNotFoundError(errno.ENOENT, "already removed")

        with mock.patch.object(util.os, "remove", side_effect=remove_then_report_missing):
            with lock:
                fd = lock._fd
        self.assert_closed(lock, fd)
        self.assertFalse(self.path.exists())

    def test_repeated_exit_does_not_remove_a_successor_lock(self):
        lock = util.FileLock(self.path)
        with lock:
            pass
        self.path.write_text("successor owner\n", encoding="ascii")
        lock.__exit__(None, None, None)
        self.assertTrue(self.path.exists(), "an already released handle does not own the new path")
        self.assertEqual(self.path.read_text(encoding="ascii"), "successor owner\n")


if __name__ == "__main__":
    unittest.main()
