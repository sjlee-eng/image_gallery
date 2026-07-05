"""Core monitoring logic for the git pull monitoring system.

The module is intentionally dependency-free (standard library only) so it can
run anywhere Python 3.8+ and git are available.

Two building blocks:

* ``RepoMonitor`` wraps a single repository and exposes the primitive git
  operations the monitor needs: ``fetch``, ``check`` and ``pull``.
* ``MonitorService`` drives one or more ``RepoMonitor`` instances on a fixed
  interval, logging activity and persisting a history of events.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional

logger = logging.getLogger("git_monitor")


class GitCommandError(RuntimeError):
    """Raised when an underlying git command exits non-zero."""

    def __init__(self, args: Iterable[str], returncode: int, stderr: str):
        self.args = list(args)
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(
            f"git {' '.join(self.args)} failed ({returncode}): {self.stderr}"
        )


def _utcnow() -> str:
    """ISO-8601 UTC timestamp, second precision."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class RepoStatus:
    """A point-in-time snapshot of a repository's sync state."""

    name: str
    path: str
    branch: str
    local_rev: str
    remote_rev: str
    behind: int  # commits the local branch is behind its upstream
    ahead: int  # commits the local branch is ahead of its upstream
    has_updates: bool
    checked_at: str = field(default_factory=_utcnow)
    error: Optional[str] = None

    def short(self) -> str:
        if self.error:
            return f"{self.name}: ERROR ({self.error})"
        state = "up to date"
        if self.has_updates:
            state = f"{self.behind} behind"
            if self.ahead:
                state += f", {self.ahead} ahead"
        elif self.ahead:
            state = f"{self.ahead} ahead"
        return f"{self.name} [{self.branch}] {state} @ {self.local_rev[:8]}"


@dataclass
class PullResult:
    """Outcome of a ``git pull`` attempt."""

    name: str
    path: str
    branch: str
    pulled: bool
    from_rev: str
    to_rev: str
    output: str
    pulled_at: str = field(default_factory=_utcnow)
    error: Optional[str] = None


class RepoMonitor:
    """Monitor and update a single local git repository."""

    def __init__(
        self,
        path: str,
        branch: Optional[str] = None,
        remote: str = "origin",
        name: Optional[str] = None,
        git_timeout: int = 120,
    ):
        self.path = Path(path).expanduser().resolve()
        self.remote = remote
        self.git_timeout = git_timeout
        if not (self.path / ".git").exists():
            raise ValueError(f"{self.path} is not a git repository")
        self.branch = branch or self._current_branch()
        self.name = name or self.path.name

    # -- low level ---------------------------------------------------------

    def _git(self, *args: str) -> str:
        """Run a git command in the repo and return trimmed stdout."""
        proc = subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True,
            text=True,
            timeout=self.git_timeout,
        )
        if proc.returncode != 0:
            raise GitCommandError(args, proc.returncode, proc.stderr)
        return proc.stdout.strip()

    def _current_branch(self) -> str:
        return self._git("rev-parse", "--abbrev-ref", "HEAD")

    @property
    def _upstream(self) -> str:
        return f"{self.remote}/{self.branch}"

    # -- operations --------------------------------------------------------

    def fetch(self) -> None:
        """Update remote-tracking refs without touching the working tree."""
        self._git("fetch", self.remote, self.branch)

    def check(self, fetch: bool = True) -> RepoStatus:
        """Return the current sync state of the repository.

        When ``fetch`` is true (the default) the remote is contacted first so
        the comparison reflects the latest upstream state.
        """
        try:
            if fetch:
                self.fetch()
            local_rev = self._git("rev-parse", self.branch)
            remote_rev = self._git("rev-parse", self._upstream)
            # left..right counts: behind = commits on upstream not local,
            # ahead = commits on local not upstream.
            counts = self._git(
                "rev-list",
                "--left-right",
                "--count",
                f"{self.branch}...{self._upstream}",
            )
            ahead_str, behind_str = counts.split()
            ahead, behind = int(ahead_str), int(behind_str)
            return RepoStatus(
                name=self.name,
                path=str(self.path),
                branch=self.branch,
                local_rev=local_rev,
                remote_rev=remote_rev,
                behind=behind,
                ahead=ahead,
                has_updates=behind > 0,
            )
        except (GitCommandError, subprocess.TimeoutExpired) as exc:
            logger.warning("check failed for %s: %s", self.name, exc)
            return RepoStatus(
                name=self.name,
                path=str(self.path),
                branch=self.branch,
                local_rev="",
                remote_rev="",
                behind=0,
                ahead=0,
                has_updates=False,
                error=str(exc),
            )

    def pull(self, ff_only: bool = True) -> PullResult:
        """Pull the tracked branch. Fast-forward-only by default for safety."""
        from_rev = ""
        try:
            from_rev = self._git("rev-parse", self.branch)
            args = ["pull", self.remote, self.branch]
            if ff_only:
                args.insert(1, "--ff-only")
            output = self._git(*args)
            to_rev = self._git("rev-parse", self.branch)
            return PullResult(
                name=self.name,
                path=str(self.path),
                branch=self.branch,
                pulled=(to_rev != from_rev),
                from_rev=from_rev,
                to_rev=to_rev,
                output=output,
            )
        except (GitCommandError, subprocess.TimeoutExpired) as exc:
            logger.error("pull failed for %s: %s", self.name, exc)
            return PullResult(
                name=self.name,
                path=str(self.path),
                branch=self.branch,
                pulled=False,
                from_rev=from_rev,
                to_rev=from_rev,
                output="",
                error=str(exc),
            )


class MonitorService:
    """Poll a set of repositories on an interval and react to updates."""

    def __init__(
        self,
        repos: List[RepoMonitor],
        interval: int = 60,
        auto_pull: bool = False,
        ff_only: bool = True,
        history_path: Optional[str] = None,
        on_update: Optional[Callable[[RepoStatus, Optional[PullResult]], None]] = None,
    ):
        self.repos = list(repos)
        self.interval = interval
        self.auto_pull = auto_pull
        self.ff_only = ff_only
        self.history_path = Path(history_path).expanduser() if history_path else None
        self.on_update = on_update
        self._stop = False

    # -- persistence -------------------------------------------------------

    def _record(self, event: dict) -> None:
        if not self.history_path:
            return
        try:
            history: List[dict] = []
            if self.history_path.exists():
                history = json.loads(self.history_path.read_text() or "[]")
            history.append(event)
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            self.history_path.write_text(json.dumps(history, indent=2))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("could not write history: %s", exc)

    # -- single sweep ------------------------------------------------------

    def poll_once(self) -> List[RepoStatus]:
        """Check every repo once, pulling/notifying as configured."""
        statuses: List[RepoStatus] = []
        for repo in self.repos:
            status = repo.check()
            statuses.append(status)
            if status.error:
                logger.error(status.short())
            else:
                logger.info(status.short())

            pull_result: Optional[PullResult] = None
            if status.has_updates and self.auto_pull and not status.error:
                pull_result = repo.pull(ff_only=self.ff_only)
                if pull_result.pulled:
                    logger.info(
                        "pulled %s: %s -> %s",
                        repo.name,
                        pull_result.from_rev[:8],
                        pull_result.to_rev[:8],
                    )
                elif pull_result.error:
                    logger.error("pull error for %s: %s", repo.name, pull_result.error)

            if status.has_updates or status.error:
                self._record(
                    {
                        "event": "check",
                        "status": asdict(status),
                        "pull": asdict(pull_result) if pull_result else None,
                    }
                )
                if self.on_update and not status.error:
                    try:
                        self.on_update(status, pull_result)
                    except Exception:  # never let a hook kill the loop
                        logger.exception("on_update hook raised")
        return statuses

    # -- loop --------------------------------------------------------------

    def stop(self) -> None:
        self._stop = True

    def run(self, max_iterations: Optional[int] = None) -> None:
        """Run the polling loop.

        ``max_iterations`` bounds the number of sweeps (useful for testing and
        one-shot runs); ``None`` means run until :meth:`stop` or Ctrl-C.
        """
        self._stop = False
        iterations = 0
        logger.info(
            "monitoring %d repo(s) every %ds (auto_pull=%s)",
            len(self.repos),
            self.interval,
            self.auto_pull,
        )
        try:
            while not self._stop:
                self.poll_once()
                iterations += 1
                if max_iterations is not None and iterations >= max_iterations:
                    break
                if not self._stop:
                    time.sleep(self.interval)
        except KeyboardInterrupt:
            logger.info("stopped by user")
