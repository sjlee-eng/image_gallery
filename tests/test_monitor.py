"""Tests for the git pull monitoring system.

Each test builds a real bare "remote" plus a local clone in a temp dir, so the
git plumbing is exercised end-to-end without touching the network.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from git_monitor import MonitorService, RepoMonitor  # noqa: E402


def _git(cwd, *args):
    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@e.com",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@e.com",
    )
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _commit(cwd, name, content="x"):
    (Path(cwd) / name).write_text(content)
    _git(cwd, "add", name)
    _git(cwd, "commit", "-m", f"add {name}")


class MonitorTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.remote = root / "remote.git"
        self.upstream = root / "upstream"  # working clone we push new commits from
        self.local = root / "local"  # the repo under monitor

        # Build a bare remote from an initial commit.
        _git(root, "init", "--bare", "-b", "main", str(self.remote))
        _git(root, "clone", str(self.remote), str(self.upstream))
        _commit(self.upstream, "README.md", "hello")
        _git(self.upstream, "push", "origin", "main")

        # The monitored clone starts in sync with the remote.
        _git(root, "clone", str(self.remote), str(self.local))

    def tearDown(self):
        self.tmp.cleanup()

    def _push_new_commit(self):
        _commit(self.upstream, "new.txt", "data")
        _git(self.upstream, "push", "origin", "main")

    # -- RepoMonitor -------------------------------------------------------

    def test_rejects_non_repo(self):
        with self.assertRaises(ValueError):
            RepoMonitor(self.tmp.name)

    def test_up_to_date(self):
        mon = RepoMonitor(str(self.local), branch="main")
        status = mon.check()
        self.assertFalse(status.has_updates)
        self.assertEqual(status.behind, 0)
        self.assertIsNone(status.error)
        self.assertEqual(mon.name, "local")

    def test_detects_upstream_commit(self):
        mon = RepoMonitor(str(self.local), branch="main")
        self.assertFalse(mon.check().has_updates)
        self._push_new_commit()
        status = mon.check()
        self.assertTrue(status.has_updates)
        self.assertEqual(status.behind, 1)
        self.assertEqual(status.ahead, 0)

    def test_pull_fast_forward(self):
        mon = RepoMonitor(str(self.local), branch="main")
        self._push_new_commit()
        before = mon.check()
        self.assertTrue(before.has_updates)
        result = mon.pull()
        self.assertTrue(result.pulled)
        self.assertNotEqual(result.from_rev, result.to_rev)
        self.assertTrue((self.local / "new.txt").exists())
        self.assertFalse(mon.check().has_updates)

    def test_pull_when_current_is_noop(self):
        mon = RepoMonitor(str(self.local), branch="main")
        result = mon.pull()
        self.assertFalse(result.pulled)
        self.assertIsNone(result.error)

    def test_detects_local_ahead(self):
        _commit(self.local, "local_only.txt")
        mon = RepoMonitor(str(self.local), branch="main")
        status = mon.check()
        self.assertEqual(status.ahead, 1)
        self.assertFalse(status.has_updates)

    # -- MonitorService ----------------------------------------------------

    def test_service_auto_pull_and_history(self):
        history = Path(self.tmp.name) / "history.json"
        mon = RepoMonitor(str(self.local), branch="main")
        service = MonitorService(
            [mon], interval=0, auto_pull=True, history_path=str(history)
        )
        self._push_new_commit()
        statuses = service.poll_once()
        self.assertTrue(statuses[0].has_updates or (self.local / "new.txt").exists())
        self.assertTrue((self.local / "new.txt").exists())

        recorded = json.loads(history.read_text())
        self.assertEqual(len(recorded), 1)
        self.assertTrue(recorded[0]["pull"]["pulled"])

    def test_service_on_update_hook(self):
        seen = []
        mon = RepoMonitor(str(self.local), branch="main")
        service = MonitorService(
            [mon], interval=0, on_update=lambda s, p: seen.append(s.name)
        )
        self._push_new_commit()
        service.poll_once()
        self.assertEqual(seen, ["local"])

    def test_service_hook_error_does_not_break_loop(self):
        def boom(status, pull):
            raise RuntimeError("nope")

        mon = RepoMonitor(str(self.local), branch="main")
        service = MonitorService([mon], interval=0, on_update=boom)
        self._push_new_commit()
        # Should not raise despite the hook blowing up.
        statuses = service.poll_once()
        self.assertEqual(len(statuses), 1)

    def test_run_max_iterations(self):
        mon = RepoMonitor(str(self.local), branch="main")
        service = MonitorService([mon], interval=0)
        service.run(max_iterations=2)  # completes without hanging


if __name__ == "__main__":
    unittest.main(verbosity=2)
