"""Command line interface for the git pull monitoring system.

Examples
--------
    # One-off status check of the current repo
    python -m git_monitor status

    # Watch the current repo every 30s and auto fast-forward when behind
    python -m git_monitor watch --interval 30 --auto-pull

    # Monitor several repos declared in a config file
    python -m git_monitor watch --config config.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

from .monitor import MonitorService, RepoMonitor


def _configure_logging(verbose: bool, log_file: Optional[str]) -> None:
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def _load_repos_from_config(config_path: str) -> tuple[List[RepoMonitor], dict]:
    """Build monitors from a JSON config.

    Schema::

        {
          "interval": 60,
          "auto_pull": false,
          "ff_only": true,
          "history": "monitor_history.json",
          "log_file": "monitor.log",
          "repos": [
            {"path": ".", "branch": "main", "remote": "origin", "name": "gallery"}
          ]
        }
    """
    data = json.loads(Path(config_path).expanduser().read_text())
    repos = [
        RepoMonitor(
            path=r["path"],
            branch=r.get("branch"),
            remote=r.get("remote", "origin"),
            name=r.get("name"),
        )
        for r in data.get("repos", [])
    ]
    if not repos:
        raise ValueError(f"no repos declared in {config_path}")
    return repos, data


def _build_from_args(args: argparse.Namespace) -> tuple[List[RepoMonitor], dict]:
    if args.config:
        return _load_repos_from_config(args.config)
    repo = RepoMonitor(
        path=args.repo,
        branch=args.branch,
        remote=args.remote,
        name=args.name,
    )
    return [repo], {}


def _print_statuses(statuses) -> None:
    width = max((len(s.name) for s in statuses), default=4)
    for s in statuses:
        if s.error:
            state = f"ERROR: {s.error}"
        elif s.has_updates:
            state = f"BEHIND {s.behind}" + (f" / AHEAD {s.ahead}" if s.ahead else "")
        elif s.ahead:
            state = f"AHEAD {s.ahead}"
        else:
            state = "up to date"
        rev = s.local_rev[:8] or "-"
        print(f"  {s.name:<{width}}  {s.branch:<20}  {rev:<8}  {state}")


def cmd_status(args: argparse.Namespace) -> int:
    repos, _ = _build_from_args(args)
    service = MonitorService(repos)
    print(f"Checking {len(repos)} repo(s)...")
    statuses = [r.check(fetch=not args.no_fetch) for r in repos]
    _print_statuses(statuses)
    return 1 if any(s.error for s in statuses) else 0


def cmd_pull(args: argparse.Namespace) -> int:
    repos, _ = _build_from_args(args)
    rc = 0
    for repo in repos:
        result = repo.pull(ff_only=not args.merge)
        if result.error:
            print(f"  {repo.name}: pull failed - {result.error}")
            rc = 1
        elif result.pulled:
            print(f"  {repo.name}: {result.from_rev[:8]} -> {result.to_rev[:8]}")
        else:
            print(f"  {repo.name}: already up to date")
    return rc


def cmd_watch(args: argparse.Namespace) -> int:
    repos, cfg = _build_from_args(args)
    interval = args.interval or cfg.get("interval", 60)
    auto_pull = args.auto_pull or cfg.get("auto_pull", False)
    ff_only = not args.merge and cfg.get("ff_only", True)
    history = args.history or cfg.get("history")
    service = MonitorService(
        repos,
        interval=interval,
        auto_pull=auto_pull,
        ff_only=ff_only,
        history_path=history,
    )
    service.run(max_iterations=args.iterations)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="git_monitor",
        description="Monitor git repositories for upstream changes and pull them.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--log-file", help="also write logs to this file")

    def add_target(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--repo", default=".", help="path to a git repo (default: .)")
        sp.add_argument("--branch", help="branch to track (default: current)")
        sp.add_argument("--remote", default="origin", help="remote name (default: origin)")
        sp.add_argument("--name", help="display name for the repo")
        sp.add_argument("--config", help="JSON config describing repos to monitor")

    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="show current sync state and exit")
    add_target(p_status)
    p_status.add_argument(
        "--no-fetch", action="store_true", help="do not contact the remote"
    )
    p_status.set_defaults(func=cmd_status)

    p_pull = sub.add_parser("pull", help="pull tracked branch(es) once")
    add_target(p_pull)
    p_pull.add_argument(
        "--merge", action="store_true", help="allow merge pulls (default: ff-only)"
    )
    p_pull.set_defaults(func=cmd_pull)

    p_watch = sub.add_parser("watch", help="continuously monitor on an interval")
    add_target(p_watch)
    p_watch.add_argument("--interval", type=int, help="seconds between checks")
    p_watch.add_argument("--auto-pull", action="store_true", help="pull when behind")
    p_watch.add_argument("--merge", action="store_true", help="allow merge pulls")
    p_watch.add_argument("--history", help="path to a JSON history log")
    p_watch.add_argument(
        "--iterations", type=int, help="stop after N checks (default: run forever)"
    )
    p_watch.set_defaults(func=cmd_watch)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose, args.log_file)
    try:
        return args.func(args)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
