# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**trusty-cage** is a host-side Python CLI tool that creates fully isolated, persistent Docker-based development environments on macOS (via OrbStack). Each environment is scoped to a single git repo, contains no git credentials, and provides an interactive dev experience (tmux + Neovim/LazyVim + Claude Code) inside a container. Work is exported back to the host for git operations.

v1 is feature-complete. The archived v1 specification is at `docs/v1-spec.md`. Planned enhancements are in `v2-spec.md`.

## Build & Development

```bash
# Setup
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run
trusty-cage --help

# Lint & format
ruff format .
ruff check --fix .

# Tests
pytest
pytest tests/test_foo.py              # single file
pytest tests/test_foo.py::test_bar    # single test

# Build & publish (requires build + twine in dev deps)
make build          # Build wheel and sdist
make publish-test   # Upload to TestPyPI
make publish        # Upload to PyPI
make help           # Show all targets
```

## Architecture

### CLI Framework

- **Typer** for CLI with **Rich** for terminal output
- All Docker operations via **subprocess calls to `docker` CLI** (not the Docker Python SDK)

### CLI Commands

The CLI is available as `trusty-cage` or the short alias `tc`.

| Command | Purpose |
|---|---|
| `init [--force]` | Create config directory and default `.env` file |
| `create <git-repo-url> [--name] [--no-attach] [--auth-mode] [--dockerfile] [--add-dir]` | Clone repo, build image, create container+volume, copy files in, init local git, apply dotfiles, attach |
| `create --dir <path> [--name] [--no-attach] [--auth-mode] [--dockerfile] [--add-dir]` | Same as above but copies from a local directory instead of cloning a URL |
| `attach <name>` | Start container if stopped, apply iptables, create/attach tmux session |
| `stop <name>` | Stop container (preserves volume) |
| `list [--json]` | Show all environments with status, date, repo URL, additional dirs |
| `exists <name>` | Check if an environment exists (exit code 0/1) |
| `add-dir <name> <path> [--name]` | Add a local directory to an existing cage (recreates container with new volume mount) |
| `remove-dir <name> <dir-name> [--yes]` | Remove an additional directory from a cage (removes volume and host clone) |
| `export <name> [--output-dir] [--delete] [--protect] [--dir] [--all]` | Copy container files → host clone via rsync (`--dir` for specific additional dirs, `--all` for everything) |
| `diff <name> [--full] [--output-dir] [--dir] [--all]` | Preview what `tc export` would change (dry-run rsync comparison; supports `--dir`/`--all`) |
| `sync <name> [--files] [--yes] [--dir] [--all]` | Push host files into cage (inverse of export; supports `--dir`/`--all`) |
| `destroy <name> [--keep-host-clone]` | Remove container, all volumes, and host clone by default. Pass `--keep-host-clone` to retain the host clone at `~/.trusty-cage/envs/<name>/`. Warns on uncommitted or unpushed work before purging (unless `--yes`). |
| `rebuild-image [--dockerfile]` | Force rebuild Docker image |
| `auth <name> [--login]` | Refresh/verify credentials; `--login` opens interactive Claude for `/login` |
| `launch <name> --prompt\|--prompt-file\|--test [--background] [--no-inject-messaging]` | Launch Claude inside a cage with proper auth handling (messaging instructions injected by default) |
| `logs <name> [-f] [--raw]` | Stream inner Claude's reasoning from outside the cage (pretty-print by default) |
| `diagnose <name> [--json]` | Run a diagnostic sweep against a cage: inner Claude process state (alive/zombie/absent), outbox activity, inside-cage git status, stream-log tail, actionable suggestion |
| `salvage <name> [--yes] [--output-dir]` | Rescue work from a cage that did not reach task_complete. Runs the diagnostic sweep, warns on alive-inner / clean-git / stopped-container, then exports into the current directory (or `--output-dir`). Cage is preserved — run `tc destroy <name>` when done. |

### Host File Layout

```
~/.trusty-cage/
  .env                 # User config (created by `trusty-cage init`)
  image.sha            # SHA of Dockerfile for rebuild detection
  envs/<name>/
    meta.json          # Source of truth: repo_url, created_at, volume_name, host_clone_path, auth_mode, additional_dirs
    repo/              # Full host clone with remotes (for export)
    dirs/<dir-name>/   # Host clones for additional directories (for export/sync)
```

### Container Setup

- Base: `ubuntu:24.04` (ARM64)
- Non-root user: `trustycage` (UID 1000), home `/home/trustycage`
- Working directory: `/home/trustycage/project` (Docker named volume: `isolated-dev-<name>`)
- No bind mounts, no SSH keys, no git credentials, no `.netrc`, no `~/.config/gh`
- `ANTHROPIC_API_KEY` injected at runtime via `docker exec -e` (never on disk)
- Dotfiles: cloned on host → `docker cp` into container (`.git/` stripped) → run install script if present

### Network Policy

Applied via `init-network.sh` at attach time (run as root, then drops to `trustycage`). Must be idempotent (use `iptables -C` before adding rules).

- **Blocked**: Port 22 (SSH) to all hosts; `hub.docker.com` / `registry-1.docker.io`
- **Allowed**: Everything else (HTTPS git, packages, web, DNS)
- Primary protection is **credential absence**, not network blocking

### Authentication Modes

Chosen at `create` time, stored in `meta.json`:

- **api_key**: Reads host env var at attach time, injected via `docker exec -e`
- **subscription**: Copies `~/.claude/` into container via `docker cp` at create time; persists in volume

## Code Conventions

### Imports
- All imports must be at the top of the file — no inline or lazy imports inside functions
- This applies to all Python files in the project

## Testing Workflow

Before committing, always:

1. **Run pytest** — all unit tests must pass (`pytest` or `pytest -v`)
2. **Install in dev mode** — `pip install -e .` to pick up changes
3. **Test from the terminal** — run `tc` commands manually to verify:
   - CLI help renders correctly for changed commands (`tc <cmd> --help`)
   - Error paths return exit code 1 with clear messages
   - Happy paths work end-to-end with a real Docker container (create, diff, export, sync, destroy)
   - Regression: existing functionality still works alongside new features

Terminal testing catches issues that unit tests with mocked Docker calls miss (argument parsing edge cases, rsync behavior, file permission issues).

## Git Workflow

- Work happens on feature branches off `main`
- Merges to `main` are done via PR on GitHub — never merge locally
- Push the feature branch and open a PR
- **Before opening a PR, update `CHANGELOG.md`** with an entry for the change (under the upcoming release, or a new version heading if cutting a release). User-facing changes must appear in the changelog.
- **Before opening a PR, run the `readme-audit` skill** to confirm `README.md` still matches the surface (CLI commands, flags, behavior) the PR touches. Fix anything drifted in the same PR. For trivial PRs (tests-only, docs-only, internal refactor) a one-line "readme-audit: no user-visible surface changed" in the PR description is enough.

## Release Workflow

- Always merge to `main` via PR **before** publishing to PyPI
- Never publish to PyPI from an unmerged branch

## Versioning

This project follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`

- **MAJOR** — breaking changes (renamed commands, changed config format, dropped features)
- **MINOR** — new features, backwards-compatible (new commands, new config options)
- **PATCH** — bug fixes, docs-only changes, no behavior change

Version is set in two places (keep in sync):
- `pyproject.toml` → `version`
- `src/trusty_cage/__init__.py` → `__version__`

**When to prompt about version bumps:** Before committing work that adds new features (minor bump) or fixes bugs (patch bump), suggest the appropriate version increment to the user. Don't bump automatically — ask first.

## Key Design Constraints

- `meta.json` is the source of truth for environment state — never infer from Docker state alone
- All operations should be **idempotent** where possible
- The tool must **never** run `git push` or configure git credentials
- Container's local git repo has no remotes — Claude Code uses git locally only
- Export uses rsync to overlay container files onto host clone, preserving host's `.git/`
- Published on PyPI as `trusty-cage` — installable via `pip install trusty-cage` or `pipx install trusty-cage`
