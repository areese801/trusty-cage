# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**trusty-cage** is a host-side Python CLI tool that creates fully isolated, persistent Docker-based development environments on macOS (via OrbStack). Each environment is scoped to a single git repo, contains no git credentials, and provides an interactive dev experience (tmux + Neovim/LazyVim + Claude Code) inside a container. Work is exported back to the host for git operations.

The full specification is in `trusty-cage-spec.md`.

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
```

## Architecture

### CLI Framework

- **Typer** for CLI with **Rich** for terminal output
- All Docker operations via **subprocess calls to `docker` CLI** (not the Docker Python SDK)

### CLI Commands

| Command | Purpose |
|---|---|
| `create <git-repo-url> [--name] [--no-attach]` | Clone repo, build image, create container+volume, copy files in, init local git, apply dotfiles, attach |
| `attach <name>` | Start container if stopped, apply iptables, create/attach tmux session |
| `stop <name>` | Stop container (preserves volume) |
| `list` | Show all environments with status, date, repo URL |
| `export <name>` | Copy container files → host clone via rsync (preserving host `.git/`) |
| `destroy <name>` | Remove container + volume (keeps host clone) |
| `rebuild-image` | Force rebuild Docker image |

### Host File Layout

```
~/.trusty-cage/
  .env                 # Optional user config (env vars, not created by tool)
  image.sha            # SHA of Dockerfile for rebuild detection
  envs/<name>/
    meta.json          # Source of truth: repo_url, created_at, volume_name, host_clone_path, auth_mode
    repo/              # Full host clone with remotes (for export)
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

## Key Design Constraints

- `meta.json` is the source of truth for environment state — never infer from Docker state alone
- All operations should be **idempotent** where possible
- The tool must **never** run `git push` or configure git credentials
- Container's local git repo has no remotes — Claude Code uses git locally only
- Export uses rsync to overlay container files onto host clone, preserving host's `.git/`
- Package structure should be kept clean for future PyPI distribution
