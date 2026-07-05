# git pull 모니터링 시스템 (git pull monitoring system)

A lightweight, dependency-free tool that watches one or more local git
repositories, periodically checks their remotes for new commits, optionally
pulls them, and records the activity.

It was built for this `image_gallery` repo so new images pushed to the remote
can be pulled and surfaced automatically, but it works with any git repository.

## Requirements

- Python 3.8+
- `git` on the `PATH`

No third-party packages are needed — the standard library only.

## Quick start

```bash
# Show the current sync state of the repo in the working directory
python -m git_monitor status

# Pull the tracked branch once (fast-forward only by default)
python -m git_monitor pull

# Watch the current repo every 30s and auto fast-forward when behind
python -m git_monitor watch --interval 30 --auto-pull

# Monitor several repos declared in a config file, logging to a file
python -m git_monitor watch --config config.json --log-file monitor.log
```

## Commands

| Command  | What it does                                                        |
|----------|---------------------------------------------------------------------|
| `status` | Fetch and print how far ahead/behind each repo is, then exit.       |
| `pull`   | Pull the tracked branch once. `--merge` allows non-fast-forward.    |
| `watch`  | Poll on an interval. `--auto-pull` pulls when behind, `--history` logs events, `--iterations N` stops after N sweeps. |

Common flags: `--repo PATH`, `--branch NAME`, `--remote NAME`, `--name LABEL`,
`--config FILE`, `-v/--verbose`, `--log-file FILE`.

## Config file

Instead of flags you can describe repos in JSON (see `config.example.json`):

```json
{
  "interval": 60,
  "auto_pull": true,
  "ff_only": true,
  "history": "monitor_history.json",
  "repos": [
    { "path": ".", "branch": "main", "remote": "origin", "name": "image_gallery" }
  ]
}
```

## History

When `--history FILE` (or `"history"` in the config) is set, every sweep that
finds updates or an error appends an entry to a JSON file, capturing the
`RepoStatus` and any `PullResult`. Useful for auditing what was pulled and when.

## Library use

```python
from git_monitor import RepoMonitor, MonitorService

repo = RepoMonitor(".", branch="main")
status = repo.check()          # fetches, returns a RepoStatus
if status.has_updates:
    repo.pull()

# Or drive several repos, reacting via a callback:
def notify(status, pull_result):
    print(f"{status.name} updated -> {status.remote_rev[:8]}")

MonitorService([repo], interval=60, auto_pull=True, on_update=notify).run()
```

## Safety notes

- Pulls are **fast-forward only** by default, so the monitor never creates
  surprise merge commits or clobbers local work. Pass `--merge` to opt in.
- A repository that is *ahead* of its upstream is reported but never pulled.
- Callback (`on_update`) exceptions are caught and logged — a bad hook can't
  crash the polling loop.

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests spin up real bare remotes and clones in a temp directory, so the git
plumbing is exercised end-to-end without any network access.
