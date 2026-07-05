"""git_monitor — a lightweight git pull monitoring system.

Watches one or more local git repositories, periodically checks their
remotes for new commits, optionally pulls them, and records the results.

Public API:
    RepoMonitor   — inspect / fetch / pull a single repository
    MonitorService — orchestrate several repositories on an interval
"""

from .monitor import RepoMonitor, MonitorService, RepoStatus, PullResult

__all__ = ["RepoMonitor", "MonitorService", "RepoStatus", "PullResult"]

__version__ = "1.0.0"
