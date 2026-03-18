# trusty-cage

Isolated Docker-based development environments for AI coding agents. Run Claude Code (or any agent) with full autonomy inside a disposable container — no risk to your host machine, no credentials exposed, no accidental pushes.

## Installation

```bash
git clone https://github.com/youruser/trusty-cage.git
cd trusty-cage
python -m venv venv
source venv/bin/activate
pip install -e .
```

`tc` is available as a shorthand for `trusty-cage` (e.g. `tc create ...`, `tc attach ...`).

## Quick Start

```bash
# Create an environment from any git repo
trusty-cage create https://github.com/octocat/Hello-World

# You're now inside a tmux session (prefix: Ctrl-a) with:
#   Window 1 (editor)  — Neovim at the project root
#   Window 2 (claude)  — Claude Code running with --dangerously-skip-permissions
#   Window 3 (shell)   — plain shell

# Switch windows with Ctrl-a <number>, detach with Ctrl-a d

# When done, export your work back to the host:
trusty-cage export hello-world

# Review and push from the host clone:
cd ~/.trusty-cage/envs/hello-world/repo/
git diff
git add -A && git commit -m "work from trusty-cage"
git push
```

## Example: Hello World

```bash
# Create (environment name is derived as lowercase: "hello-world")
trusty-cage create https://github.com/octocat/Hello-World --no-attach

# Verify
trusty-cage list
docker ps -a | grep isolated-dev

# Attach — drops you into tmux inside the container
trusty-cage attach hello-world

# Inside the container:
#   Ctrl-a w          — list tmux windows
#   git remote -v     — empty (no remotes, by design)
#   curl example.com  — works (outbound web allowed)
#   Ctrl-a d          — detach

# Export work back to host
trusty-cage export hello-world

# Clean up
trusty-cage destroy hello-world
```

## Commands

| Command | Description |
|---|---|
| `trusty-cage create <url> [--name NAME] [--no-attach]` | Create a new environment from a git repo |
| `trusty-cage attach <name>` | Attach to an existing environment |
| `trusty-cage stop <name>` | Stop a container (preserves work) |
| `trusty-cage list` | List all environments with status |
| `trusty-cage export <name>` | Copy work back to host clone |
| `trusty-cage destroy <name>` | Remove container and volume (keeps host clone) |
| `trusty-cage rebuild-image` | Force rebuild the Docker image |

## Configuration

Configuration is resolved in order: CLI flags > environment variables > `~/.trusty-cage/.env` > defaults.

| Variable | Default | Description |
|---|---|---|
| `TRUSTY_CAGE_DOTFILES_REPO` | *(empty)* | HTTPS URL of dotfiles repo to clone into containers |
| `TRUSTY_CAGE_PYTHON_VERSION` | `3.12` | Python version installed via pyenv |
| `TRUSTY_CAGE_DEFAULT_SHELL` | `zsh` | Default shell inside the container |
| `TRUSTY_CAGE_DEFAULT_AUTH_MODE` | `api_key` | Auth mode: `api_key` or `subscription` |
| `TRUSTY_CAGE_TMUX_PREFIX` | `C-a` | tmux prefix key inside containers (default `Ctrl-a` to avoid conflict with host `Ctrl-b`) |

To set persistent defaults, copy the example file to `~/.trusty-cage/.env`:

```bash
mkdir -p ~/.trusty-cage
cp .env.example ~/.trusty-cage/.env
# edit ~/.trusty-cage/.env with your values
```

**Important:** The `.env` file must live at `~/.trusty-cage/.env`, not at the project root. This keeps your config independent of where you cloned the repo and persists across reinstalls.

## Authentication

Chosen at `create` time:

- **api_key** — Reads `ANTHROPIC_API_KEY` from your host shell at attach time. Injected via `docker exec -e`, never written to disk.
- **subscription** — Copies `~/.claude/` credentials into the container at create time. Persists in the volume.

## Security Model

The container is the blast radius. If an agent does something destructive, your host is unaffected.

**What agents can do inside:**
- Clone/fetch public repos over HTTPS
- Browse the web, read docs, hit public APIs
- Install packages (pip, apt, npm)
- Full read/write access to the project directory

**What agents cannot do:**
- Push to any git remote (no credentials present)
- Use SSH (port 22 blocked)
- Pull Docker images from Docker Hub (blocked)
- Access any host files (no bind mounts)

Protection is enforced by **credential absence**, not network blocking. The container has no SSH keys, no `.netrc`, no `GH_TOKEN`, no git credential helper.

## Requirements

- macOS with OrbStack or Docker Desktop
- Python 3.11+
- Git

## License

MIT
