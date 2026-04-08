# Changelog

All notable changes to trusty-cage are documented here.

This project follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

---

## [Unreleased]

### Added
- **Auto-rebuild stale Docker image.** `tc create` and `tc attach` now automatically rebuild the Docker image when the Dockerfile has changed, instead of just warning. Disable with `TRUSTY_CAGE_AUTO_REBUILD=false` in `~/.trusty-cage/.env`.
- **`cage-wait` command.** New helper installed in containers alongside `cage-send`. Blocks until a new inbox message arrives (adaptive polling: 10s/30s/60s). Prints diagnostic timestamps to stderr for tracing revision pickup latency. Replaces the need for inner agents to copy a 25-line inline polling script.
- **Post-export file-change summary.** `tc export` now prints a concise summary (N added, N modified, N deleted) after each export by inspecting `git status` in the host clone.

### Changed
- **Stronger `progress_update` wording in messaging instructions.** Inner Claude is now told it MUST send updates every 3 minutes or the host will assume it is stuck. Previously said "every few minutes" which was routinely ignored.
- **Image staleness check moved from `check_for_updates()` to `build_if_needed()`.** Eliminates the redundant "Docker image is outdated" warning when auto-rebuild is about to handle it.

## [0.8.7] - 2026-04-04

### Added
- **Version check on startup** — `tc create` and `tc attach` now check PyPI for newer versions and detect stale Docker images (when Dockerfile SHA has changed). Silent on network failure (3s timeout). No new dependencies.
- **Payload schema validation in `cage-send`** — inner agents sending malformed messages now get clear error messages with the missing/wrong fields. Required fields per message type are enforced (e.g. `task_complete` requires `summary: str` and `exit_code: int`).

## [0.8.6] - 2026-04-04

### Fixed
- **`.gitignore` now transfers from cage to host on export.** Previously hardcoded as an rsync exclude, meaning agent modifications to `.gitignore` inside the cage were silently dropped. Users who want to preserve the host's `.gitignore` can list it in `.cageprotect`.

### Changed
- Expanded README documentation of `.cageprotect` with clearer explanation of hardcoded vs config-driven excludes.

## [0.8.5] - 2026-04-01

### Fixed
- **Ghost work bug.** `tc destroy` preserves the host clone directory (for exported work retrieval), but `tc create` had a "Reusing existing host clone" code path that copied those stale files into fresh cages — producing files from previous sessions. Now the stale env directory is wiped when recreating a cage with the same name.
- `--dir` mode rsync now excludes `venv/`, `.venv/`, and `__pycache__/` from the source copy.

## [0.8.4] - 2026-03-31

### Fixed
- **Orphaned Docker volume cleanup.** If `tc destroy` was interrupted or a container lingered, the next `tc create` with the same name would silently reuse the orphaned volume. Now detects and removes both orphaned containers and volumes before creating fresh ones.

## [0.8.3] - 2026-03-31

### Changed
- **`tc logs` pretty-print improvements.** Color-coded output with better visual hierarchy: `THINKING` collapsed to first line (dim italic), `TOOL` yellow labels with dimmed tool name, `RESULT` fully dimmed, `CLAUDE` bold white (stands out), `DONE` green. Added formatting for `Read`, `Grep`, `Glob` tools (was only `Bash`/`Write`/`Edit`).

## [0.8.2] - 2026-03-31

### Added
- **Timestamps in `tc logs`** — `HH:MM:SS` prefix on every pretty-printed line (wall-clock time as lines are read).
- **Timestamps in `tc outbox --poll`** — extracts `HH:MM:SS` from message ISO-8601 timestamps, shown on all progress/error/task_complete/going_idle messages.
- **`venv/` protection on export** — `tc export` always excludes `venv/` and `.venv/` from rsync regardless of `.gitignore`, preventing `--delete` from nuking host virtual environments.

## [0.8.1] - 2026-03-30

### Added
- **`--stats` flag on `tc export` and `tc diff`** — shows per-language table of lines added/removed/modified. Uses `cloc --diff --json` when installed, falls back to pure-Python line counter using `difflib` and file extension mapping. No new dependencies.

## [0.8.0] - 2026-03-30

### Added
- **Additional directories support** — ship multiple local directories into a cage alongside the main project, each with its own Docker volume and host clone.
  - `tc add-dir <name> <path>` — add a directory to an existing cage (recreates container with new volume mount)
  - `tc remove-dir <name> <dir-name>` — remove an additional directory
  - `--add-dir <path>` on `tc create` — include directories at cage creation time
  - `--dir <name>` / `--all` on `tc export`, `tc sync`, `tc diff` — target specific additional dirs
  - `tc list` shows additional dirs column
  - `tc destroy` cleans up all additional dir volumes and host clones
- **`--dir <path>` flag on `tc create`** — create a cage from a local directory instead of cloning a URL (landed earlier in this release cycle).

### Fixed
- **git config re-applied after container recreation** — `~/.gitconfig` lives in the container filesystem (not a volume) and gets lost on recreation, so `add-dir`/`remove-dir` would fail on git init. Now re-applied automatically.
- **rsync `-i` itemize parsing** — fixed to work with both GNU rsync (11-char flags) and macOS openrsync (9-char flags). Split on whitespace instead of hardcoded offsets.

---

## Earlier Releases

See git history for versions prior to 0.8.0.
