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

## Quick Start

```bash
# Create an environment from any git repo
trusty-cage create https://github.com/org/myrepo

# You're now inside a tmux session with:
#   Window 1 (editor)  — Neovim at the project root
#   Window 2 (claude)  — Claude Code running with --dangerously-skip-permissions
#   Window 3 (shell)   — plain shell

# When done, detach from tmux (Ctrl-b d), then export your work:
trusty-cage export myrepo

# Review and push from the host clone:
cd ~/.trusty-cage/envs/myrepo/repo/
git diff
git add -A && git commit -m "work from trusty-cage"
git push
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

Create `~/.trusty-cage/.env` to set persistent defaults:

```bash
TRUSTY_CAGE_DOTFILES_REPO=https://github.com/youruser/dotfiles
TRUSTY_CAGE_PYTHON_VERSION=3.12
```

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
