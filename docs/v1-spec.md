# trusty-cage — v1 Specification (Archived)

> **This is the archived v1 specification.** v1 is feature-complete. For current project guidance, see `CLAUDE.md`. For planned enhancements, see `v2-spec.md`.

## Overview

A host-side Python CLI tool (`trusty-cage`) that creates fully isolated, persistent Docker-based development environments on macOS (via OrbStack). Each environment is scoped to a single git repository, contains no git credentials and cannot write to any remote, and provides a complete interactive development experience (tmux + Neovim/LazyVim + Claude Code) inside the container. Work produced inside the environment is exported back to the host's local clone via a separate explicit workflow, where the user handles all git operations (branching, committing, pushing, PR creation) on trusted ground.

The tool is designed to support Claude Code in v1, with the architecture deliberately kept agent-agnostic so that other coding agents (e.g. Aider, Goose, Codex) can be added in future versions without structural changes.

### Motivation

AI coding agents like Claude Code are most productive when given autonomy -- the ability to read files, write files, execute commands, and iterate without stopping to ask for permission at every step. Claude Code exposes this via flags like `--dangerously-skip-permissions` and `--enable-auto-mode`, which suppress the approval prompts that interrupt agentic workflows.

The problem is that these flags are genuinely dangerous on a host machine. An agent running without guardrails can delete files, modify configuration, or cause damage that is difficult to reverse. The flags exist for good reason but should never be used directly against a developer's real environment.

`trusty-cage` solves this by providing a disposable, isolated container where these flags are safe to use. The container is the blast radius. If Claude Code does something destructive inside it, the host machine is completely unaffected -- the developer simply destroys the environment and starts fresh. This lets users get the full productivity benefit of autonomous agent operation without exposing their real system to risk.

---

## Goals

- Claude Code (and any other process inside the container) **cannot push to or damage any remote git repository** -- write operations are impossible due to the absence of any credentials, and SSH is blocked at the network level.
- The host macOS filesystem is **never bind-mounted** into the container. No host files are at risk.
- Environments are **persistent** across stop/start cycles -- work survives restarts.
- The interactive experience inside the container is **first-class**: tmux, Neovim/LazyVim, Claude Code, a full shell, and a Python runtime are all pre-installed.
- The tool is **simple to operate** -- one command to create, one to attach, one to export.

---

## Non-Goals (explicitly out of scope for v1)

- Multi-language runtime support beyond Python (Node.js, Go, Rust can be added later)
- Running on bare metal Linux (the architecture supports it -- OrbStack is simply not installed, Docker Engine is used directly -- but no special handling is built for it now)
- Networked collaboration or shared environments
- Automated PR creation (the export workflow stops at "files are back on the host")
- Support for coding agents other than Claude Code (architecture is agent-agnostic by design; other agents are a future addition)
- Support for additional host operating systems beyond macOS (Windows WSL2, bare metal Linux)
- Distribution via PyPI (`pip install trusty-cage` / `pipx install trusty-cage`) -- the package structure should be kept clean from v1 with this goal in mind
- Optional opt-in git write access -- a future configuration option allowing a developer who understands the implications to supply credentials and configure a remote inside the environment (e.g. for a full in-container workflow without the export step)

---

## Architecture

### Host side

```
~/.trusty-cage/
  .env                 # Optional user config (env vars, not created by tool)
  envs/
    <env-name>/
      meta.json        # Repo URL, creation date, Docker volume name, host clone path
```

A single Python CLI package, installable via `pip install -e .` or `pipx`, providing the `trusty-cage` command (also available as `tc` for convenience).

### Container side

- Base image: `ubuntu:24.04` (ARM64 -- native on M4 Max, no emulation)
- One Docker named volume per environment, mounted at `/home/trustycage/project` inside the container
- No bind mounts to the host filesystem
- No SSH keys, no git credentials, no git credential helpers configured
- Network policy: default-allow outbound. Port 22 (SSH) and Docker Hub are blocked. All other traffic including public HTTPS git access is permitted. See Network Policy section.
- `ANTHROPIC_API_KEY` injected at runtime via environment variable -- never baked into the image

---

## Configuration

Configuration is resolved in this order (highest priority first):

1. **CLI flags** — per-invocation overrides (e.g. `--python-version 3.13`)
2. **Environment variables** — set in the shell or exported in a profile
3. **`~/.trusty-cage/.env`** — persistent local defaults (git-ignored, user-managed)
4. **Built-in defaults** — sensible fallbacks

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TRUSTY_CAGE_DOTFILES_REPO` | *(empty)* | HTTPS URL of dotfiles repo to clone into containers |
| `TRUSTY_CAGE_PYTHON_VERSION` | `3.12` | Python version installed via pyenv in the container |
| `TRUSTY_CAGE_DEFAULT_SHELL` | `zsh` | Default shell inside the container |
| `TRUSTY_CAGE_DEFAULT_AUTH_MODE` | `api_key` | Authentication mode: `api_key` or `subscription` |
| `ANTHROPIC_API_KEY` | *(none)* | API key for Claude Code (required for `api_key` auth mode) |

### `.env` file

Users can create `~/.trusty-cage/.env` to set persistent defaults:

```bash
TRUSTY_CAGE_DOTFILES_REPO=https://github.com/youruser/dotfiles
TRUSTY_CAGE_PYTHON_VERSION=3.12
TRUSTY_CAGE_DEFAULT_SHELL=zsh
TRUSTY_CAGE_DEFAULT_AUTH_MODE=api_key
```

The `.env` file is loaded automatically via `python-dotenv` but never created or modified by the tool. It is the user's responsibility to create and maintain it.

---

## Authentication

Claude Code supports two authentication modes. `trusty-cage` prompts the user to choose at `create` time and stores the choice in `meta.json`.

### API Key mode

The `ANTHROPIC_API_KEY` is read from the named host environment variable at `attach` time and injected into the container as an environment variable via `docker exec -e`. It is never written to disk inside the container and never baked into the image.

### Subscription mode (Claude account)

Claude Code stores session credentials in `~/.claude/` after a `claude login` flow. To bootstrap this inside the container:

1. At `create` time, if subscription mode is chosen and `~/.claude/` exists on the host, `trusty-cage` copies it into the container via `docker cp` (same pattern as dotfiles -- no git remote, just files)
2. If `~/.claude/` does not exist on the host, the user is prompted to run `claude login` on the host first, then re-run `trusty-cage create`
3. The copied credentials are stored in the named volume, so they persist across container stop/start cycles
4. Claude Code inside the container uses these credentials directly -- no re-authentication needed

**Security note:** subscription credentials inside the container have the same network restrictions as everything else -- `api.anthropic.com` is reachable (required for Claude Code to function in either auth mode), and general outbound access is permitted.

### meta.json auth fields

```json
{
  "auth_mode": "api_key",           // or "subscription"
  "api_key_env": "ANTHROPIC_API_KEY" // only present when auth_mode is "api_key"
}
```

---

## Docker Image

A single `Dockerfile` maintained alongside the tool. Built once locally, tagged as `trusty-cage:latest`. Rebuilt only when the Dockerfile changes (the tool detects this via a SHA of the Dockerfile stored in `~/.trusty-cage/image.sha`).

### Dockerfile contents

- Base: `ubuntu:24.04` (ARM64)
- System packages: `git`, `curl`, `wget`, `tmux`, `zsh`, `ripgrep`, `fd-find`, `fzf`, `build-essential`, `iptables`
- Neovim: latest AppImage or compiled from source (pinned version)
- Node.js: LTS (required by Claude Code and LazyVim Mason installs -- not exposed as a user runtime)
- Claude Code: `npm install -g @anthropic-ai/claude-code`
- Python: installed via `pyenv` at the version specified in config (defaults to 3.12)
- Non-root user: `trustycage` (UID 1000), home at `/home/trustycage`
- Working directory: `/home/trustycage/project`
- Default shell: `zsh`
- No SSH keys, no git credentials, no `.netrc`, no `~/.config/gh`

### Dotfiles bootstrap

At **container creation time** (not baked into the image), the tool:

1. Clones the dotfiles repo on the **host** into a temp directory
2. Copies the files into the container via `docker cp` (strips `.git/` entirely)
3. Runs the dotfiles install script inside the container if one exists (e.g. `install.sh` or `bootstrap.sh`), otherwise just copies files into place
4. The container has no knowledge of where the dotfiles came from

---

## CLI Commands

### `trusty-cage create <git-repo-url> [--name <name>]`

The primary entry point.

**What it does:**

1. Validates that OrbStack/Docker is running
2. Derives an environment name from the repo URL if `--name` is not provided (e.g. `github.com/org/myrepo` → `myrepo`)
3. Checks that no environment with that name already exists
4. Clones the repo to `~/.trusty-cage/envs/<name>/repo/` on the host (this is the host clone -- full git history, remotes intact, used for export later)
5. Builds the Docker image if not already built (or if the Dockerfile has changed)
6. Creates a Docker named volume: `isolated-dev-<name>`
7. Creates and starts a container named `isolated-dev-<name>`
8. Copies the repo files (without `.git/`) into `/home/trustycage/project/` inside the container via `docker cp`
9. Initialises a **local git repo** inside the container at `/home/trustycage/project/` with the project files as an initial commit -- no remotes configured, so Claude Code can use git locally without any connection to the outside world
10. Clones the dotfiles repo on the host, copies files into the container via `docker cp`, runs install script if present
11. Writes `~/.trusty-cage/envs/<name>/meta.json`
12. Attaches to the container (equivalent to `trusty-cage attach <name>`)

**Flags:**

- `--name <name>` -- override the derived environment name
- `--no-attach` -- create but don't attach immediately

---

### `trusty-cage attach <name>`

Attaches to an existing environment's interactive tmux session.

**What it does:**

1. Starts the container if stopped (`docker start`)
2. Applies the iptables network policy (run as root inside container, then drops to `trustycage` user) -- idempotent, safe to re-apply
3. Checks whether a tmux session named `dev` already exists inside the container
4. If not: creates a new tmux session with a 3-pane layout in a single window:
   - Left pane (60%): Neovim/LazyVim opened at `/home/trustycage/project/`
   - Top-right pane: `claude --dangerously-skip-permissions`
   - Bottom-right pane: plain shell
5. Attaches via `docker exec -it isolated-dev-<name> tmux attach -t dev`

---

### `trusty-cage stop <name>`

Stops the container without destroying it or the volume. Work is preserved.

```
docker stop isolated-dev-<name>
```

---

### `trusty-cage list`

Lists all environments with their status (running/stopped), creation date, and source repo URL.

---

### `trusty-cage export <name>`

Copies work from inside the container back to the host clone, ready for the user to branch, commit, and push.

**What it does:**

1. Confirms the operation with the user (shows what will be overwritten)
2. Copies `/home/trustycage/project/` from inside the container to a temp staging directory on the host (via `docker cp`)
3. Strips the container's local `.git/` from the staging copy
4. Uses `rsync` to sync the staging copy into `~/.trusty-cage/envs/<name>/repo/` on the host, **preserving the host's existing `.git/`** (so remotes, branches, and history are intact)
5. Prints a suggested next-step workflow:
   ```
   cd ~/.trusty-cage/envs/<name>/repo/
   git checkout -b claude/my-changes
   git add -A
   git diff --stat HEAD
   git commit -m "..."
   git push origin claude/my-changes
   # open PR from here
   ```

The user reviews the diff and handles all git operations themselves. Nothing is committed or pushed automatically.

---

### `trusty-cage destroy <name>`

Destroys the container and its named volume. Prompts for confirmation. Does **not** delete the host clone at `~/.trusty-cage/envs/<name>/repo/`.

---

### `trusty-cage rebuild-image`

Rebuilds the Docker image from scratch. Useful after Dockerfile changes. Does not affect existing running environments (they continue using the old image until recreated).

---

## Network Policy

Applied inside the container at attach time via an `init-network.sh` script run as root, then the session drops to the `trustycage` user. Policy is idempotent.

The philosophy is **default-allow with minimal targeted blocking**. Claude Code should be able to browse the web freely, read public documentation, clone public repos, and fetch packages -- anything achievable without authentication. Protection against destructive git operations is enforced by the **absence of credentials**, not by network blocking.

**Policy: default-allow outbound, with two targeted blocks.**

**Blocked outbound:**
- Port 22 (SSH) to all hosts -- blocks git-over-SSH universally, the one transport that could theoretically be abused even without explicit credentials
- `hub.docker.com`, `registry-1.docker.io` -- prevents Claude Code from pulling new Docker images from inside the container

**Always allowed:**
- All other outbound TCP/UDP -- general web, git HTTPS (read-only), package registries, documentation, public APIs
- DNS (port 53)

**Why credential absence is the primary protection:**

Read-only git access over HTTPS (e.g. `git clone https://github.com/org/repo`) is explicitly permitted and useful. Write operations (`git push`) require authentication. The container has no SSH keys, no `~/.netrc`, no `GH_TOKEN`, no `~/.config/gh`, and no git credential helper configured. Without credentials, HTTPS git push fails at the protocol level regardless of what Claude Code attempts. This is a simpler and more maintainable model than maintaining a domain blocklist.

**What Claude Code can do:**
- Clone and fetch public repos over HTTPS
- Search the web, read documentation, hit public APIs
- Install packages via pip, apt, npm

**What Claude Code cannot do:**
- Push to any remote (no credentials)
- Use SSH-based git (port 22 blocked)
- Pull Docker images from Docker Hub (blocked)
- Authenticate to any service (no tokens, keys, or credentials of any kind present)

---

## Security Properties

| Threat | Mitigation |
|---|---|
| Claude Code runs `rm -rf /` | Damage contained to the named volume. Host unaffected. |
| Claude Code attempts `git push` | No credentials in the container -- HTTPS push fails at auth. No SSH keys and port 22 blocked -- SSH push impossible. |
| Claude Code damages dotfiles remote | Dotfiles cloned on host, copied into container as plain files with `.git/` stripped. No remote configured, no credentials to authenticate a push. |
| Claude Code exfiltrates secrets | Only `ANTHROPIC_API_KEY` (api_key mode) or Claude session token (subscription mode) are present. General outbound web access is permitted but no credentials exist to authenticate to any sensitive service. |
| Container escape | On macOS, escape lands in Docker's Linux VM, not the Mac. Named volumes don't touch host filesystem. |

---

## File Layout (host)

```
~/.trusty-cage/
  .env                             # Optional user config (env vars, not created by tool)
  image.sha                        # SHA of Dockerfile, used to detect when rebuild is needed
  envs/
    myrepo/
      meta.json                    # { repo_url, created_at, volume_name, host_clone_path, auth_mode }
      repo/                        # Full host clone with remotes intact (for export)
```

> **Note:** The Dockerfile is bundled in the Python package at `trusty_cage/assets/Dockerfile`, not copied to `~/.trusty-cage/`.

---

## Implementation Notes for Claude Code

- Use **Typer** for the CLI (`pip install typer[all]`)
- Use **Rich** for terminal output (already a Typer dependency)
- All Docker operations via **subprocess calls to the `docker` CLI** -- do not use the Docker Python SDK (adds a dependency and is less transparent)
- All operations should be **idempotent** where possible -- re-running `create` on an existing env should give a clear error, not corrupt state
- `meta.json` is the source of truth for environment state -- always read from it, never infer from Docker state alone
- The tool should **never** run `git push` or configure git credentials on behalf of the user -- all write operations to remotes are the user's responsibility on the host
- iptables rules in `init-network.sh` should use `-C` to check before adding (idempotent)
- The Dockerfile should use a **non-root user** (`trustycage`, UID 1000) as the default. The network init script is the only thing that needs root, and it should drop to the `trustycage` user at the end.

---

## License

MIT. Anyone can use, modify, distribute, or commercialize this project without restriction beyond retaining the copyright notice.

---

## Out of Scope (future work)

- `trusty-cage snapshot <name>` -- checkpoint a volume to a tarball
- Multiple language runtimes (Node.js as a user runtime, Go, Rust)
- A `trusty-cage clone <name> <new-name>` command to fork an environment
- Bare metal Linux host support (architecturally free -- just swap OrbStack for Docker Engine)
- `trusty-cage logs <name>` -- tail container stdout
