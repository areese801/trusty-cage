# trusty-cage

Isolated Docker-based development environments for AI coding agents. Run Claude Code (or any agent) with full autonomy inside a disposable container — no risk to your host machine, no credentials exposed, no accidental pushes.

## Installation

```bash
pip install trusty-cage
```

Or with [pipx](https://pipx.pypa.io/) for isolated CLI installs:

```bash
pipx install trusty-cage
```

`tc` is available as a shorthand for `trusty-cage` (e.g. `tc create ...`, `tc attach ...`).

## Quick Start

```bash
# One-time setup: create config directory and default .env file
trusty-cage init

# Create an environment from any git repo
trusty-cage create https://github.com/octocat/Hello-World

# You're now inside a tmux session (prefix: Ctrl-a) with:
#   Left pane (60%)  — Neovim at the project root
#   Top-right pane   — Claude Code running with --dangerously-skip-permissions
#   Bottom-right pane — plain shell
#
# If you configured TRUSTY_CAGE_DOTFILES_REPO, your shell config, aliases,
# tmux settings, and Neovim config are already applied — the container
# should feel like your own machine.

# Switch panes with Ctrl-a <arrow>, detach with Ctrl-a d

# When done, export your work back to the host:
trusty-cage export hello-world

# Review and push from the host clone:
cd ~/.trusty-cage/envs/hello-world/repo/
git diff
git add -A && git commit -m "work from trusty-cage"
git push

# Or copy into an existing clone (don't forget the trailing /):
cd ~/projects/hello-world
cp -R ~/.trusty-cage/envs/hello-world/repo/ .
```

## Demo

Here's a real workflow using trusty-cage to build an [Obsidian plugin](https://github.com/areese801/obsidian-todoist) from scratch.

### 1. Give instructions inside the cage

![Inside the cage — giving Claude Code instructions](https://raw.githubusercontent.com/areese801/trusty-cage/main/.images/trusty-cage-inside-instructions.png)

The terminal title bar shows the `tc create` command that built this environment. Inside, Claude Code runs with full autonomy (`bypass permissions on`) in a tmux session alongside Neovim. The container's git repo has **no remotes** — the agent can commit locally but has no way to push anywhere.

### 2. Let the agent work autonomously

![Claude Code working autonomously](https://raw.githubusercontent.com/areese801/trusty-cage/main/.images/trusty-cage-inside-auto-work.png)

Claude Code explored a reference project, designed an architecture, wrote the full plugin (TypeScript, settings UI, API client, parser), and committed everything — all without any human intervention. The agent had full control inside the container: installing packages, creating files, running builds. If anything went wrong, the host machine would be completely unaffected.

### 3. Export and review on the host

![Exporting work back to the host](https://raw.githubusercontent.com/areese801/trusty-cage/main/.images/trusty-cage-outside-export-work.png)

Back on the host, `tc export` copies the container's work into the host clone at `~/.trusty-cage/envs/<name>/repo/`. From there, you review the diff, commit, and push — the human stays in the loop for all git operations that touch a remote.

**To work from the exported repository:**

```bash
cd ~/.trusty-cage/envs/obsidian-todoist/repo/
git diff
git add -A && git commit -m "work from trusty-cage"
git push
```

**To copy exported code into your own cloned repository:**

If you already have the repo cloned elsewhere (e.g. `~/projects/personal/obsidian-todoist`), you can copy the exported files into it instead. Make sure you're `cd`'d into your clone first, and **don't forget the trailing `/`** on the source path — on macOS (BSD `cp`), the trailing `/` copies the *contents* of the directory rather than the directory itself:

```bash
cd ~/projects/personal/obsidian-todoist
cp -R ~/.trusty-cage/envs/obsidian-todoist/repo/ .
git status   # review what changed
git diff
git add -A && git commit -m "work from trusty-cage"
git push
```

**Linux note:** GNU `cp` ignores the trailing `/` and always copies the directory itself. On Linux, use `cp -RT` or `rsync -a` instead:

```bash
cp -RT ~/.trusty-cage/envs/obsidian-todoist/repo .
rsync -a ~/.trusty-cage/envs/obsidian-todoist/repo/ .
```

> The `Permission denied` errors on `.git/objects/pack` files are expected and harmless — your host `.git/` is preserved and those locked pack files don't need to be overwritten.

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
#   Ctrl-a <arrow>    — switch tmux panes
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
| `trusty-cage --version` | Show version and exit |
| `trusty-cage init [--force]` | Create config directory and default `.env` file |
| `trusty-cage create <url> [--name] [--no-attach] [--auth-mode] [--dockerfile]` | Create a new environment from a git repo |
| `trusty-cage attach <name>` | Attach to an existing environment |
| `trusty-cage stop <name>` | Stop a container (preserves work) |
| `trusty-cage list [--json]` | List all environments with status |
| `trusty-cage exists <name>` | Check if an environment exists (exit code 0/1) |
| `trusty-cage export <name> [--yes] [--output-dir]` | Copy work back to host clone |
| `trusty-cage destroy <name> [--yes]` | Remove container and volume (keeps host clone) |
| `trusty-cage rebuild-image [--dockerfile]` | Force rebuild the Docker image |
| `trusty-cage auth <name> [--login]` | Refresh or verify credentials for an environment |
| `trusty-cage launch <name> --prompt\|--prompt-file\|--test [--background]` | Launch Claude Code inside a cage |
| `trusty-cage logs [name] [-f] [--raw]` | Stream inner Claude's reasoning (pretty-printed by default) |

## Configuration

Configuration is resolved in order: CLI flags > environment variables > `~/.trusty-cage/.env` > defaults.

| Variable | Default | Description |
|---|---|---|
| `TRUSTY_CAGE_DOTFILES_REPO` | *(empty)* | HTTPS URL of dotfiles repo to clone into containers |
| `TRUSTY_CAGE_PYTHON_VERSION` | `3.12` | Python version installed via pyenv |
| `TRUSTY_CAGE_DEFAULT_SHELL` | `zsh` | Default shell inside the container |
| `TRUSTY_CAGE_DEFAULT_AUTH_MODE` | `api_key` | Auth mode: `api_key` or `subscription` |
| `TRUSTY_CAGE_TMUX_PREFIX` | `C-a` | tmux prefix key inside containers (default `Ctrl-a` to avoid conflict with host `Ctrl-b`) |
| `ANTHROPIC_API_KEY` | *(none)* | API key for Claude Code (required for `api_key` auth mode) |

Run `trusty-cage init` to create `~/.trusty-cage/.env` with a commented template you can customize.

## Dotfiles

If you set `TRUSTY_CAGE_DOTFILES_REPO`, your dotfiles are automatically applied to every new container at `create` time. The repo is cloned on the host, `.git/` is stripped, and the files are copied into the container's home directory. If an install script is found (`install.sh`, `setup.sh`, `bootstrap.sh`, etc.), it runs automatically. GNU Stow layouts are detected and handled (files are copied from `common/` if present).

This means your shell config, tmux settings, Neovim config, aliases, and other personalizations carry over — the container feels like your own machine.

**Without dotfiles**, the container ships with sensible defaults: oh-my-zsh (robbyrussell theme), LazyVim starter config, pyenv on PATH, and `vim`/`vi` aliased to `nvim`. Everything works out of the box, just without your personal customizations.

## Authentication

Chosen at `create` time via `--auth-mode`:

- **api_key** — Reads `ANTHROPIC_API_KEY` from your host shell at attach/launch time. Injected via `docker exec -e`, never written to disk. Best for API billing users.
- **subscription** — Copies `~/.claude/`, `~/.claude.json`, and OAuth tokens from macOS Keychain into the container at create time. Persists in the volume. Best for Claude Pro/Max subscribers — no API key needed.

```bash
# Create with API key auth (default)
tc create https://github.com/user/repo
# Requires ANTHROPIC_API_KEY to be set in your shell

# Create with subscription auth (Claude Pro/Max)
tc create https://github.com/user/repo --auth-mode subscription
# Automatically extracts OAuth tokens from macOS Keychain

# Refresh credentials at any time
tc auth myenv

# If subscription tokens have expired, re-login interactively
tc auth myenv --login
```

On macOS, subscription mode extracts OAuth tokens from the system Keychain (`Claude Code-credentials`) and writes them as `~/.claude/.credentials.json` inside the container. This bridges macOS Keychain storage with Linux's file-based fallback — no manual `/login` step needed.

## Custom Dockerfile

By default, trusty-cage uses a built-in Dockerfile (Ubuntu 24.04 with Python, Node.js, Neovim, tmux, Claude Code). You can replace it entirely with your own:

```bash
# Via CLI flag (highest priority)
tc create https://github.com/user/repo --dockerfile /path/to/Dockerfile

# Via convention path (used if no flag is passed)
# Place your Dockerfile at ~/.trusty-cage/Dockerfile

# Rebuild the image with a custom Dockerfile
tc rebuild-image --dockerfile /path/to/Dockerfile
```

Custom Dockerfiles fully replace the default — you are responsible for including the `trustycage` user (UID 1000), required tools, and any security constraints your workflow requires.

## Orchestration

trusty-cage supports two modes of use:

1. **Interactive** — `tc attach` drops you into a tmux session with Claude Code, Neovim, and a shell. You prompt Claude directly and watch it work.
2. **Headless** — `tc launch` runs Claude non-interactively with a prompt. An outer Claude (or script) orchestrates the inner Claude, monitors progress, and exports results.

### Headless Workflow

```bash
# Create a cage (no interactive attach)
tc create https://github.com/user/repo --name myproject --auth-mode subscription --no-attach

# Verify Claude can start (pre-flight check)
tc launch myproject --test

# Send a task
tc launch myproject --prompt "Implement feature X" --background

# Watch the inner Claude's reasoning in real-time (from the host)
tc logs myproject -f

# Or get raw stream-json for programmatic consumption
tc logs myproject -f --raw

# For long prompts, use a file
tc launch myproject --prompt-file /path/to/prompt.txt --background

# When done, export and overlay onto your working directory
tc export myproject --yes --output-dir .

# Clean up
tc destroy myproject --yes
```

### Monitoring with `tc logs`

`tc logs` streams the inner Claude's reasoning from outside the cage — no attach needed. Output is pretty-printed by default:

```
INIT session=a48c7ada... model=claude-opus-4-6[1m]
THINKING Simple task - create a weather.py script with temperature conversion.
TOOL Write: /home/trustycage/project/weather.py
RESULT File created successfully at: /home/trustycage/project/weather.py
TOOL Bash: python weather.py
RESULT 0°C = 32.00°F ...
CLAUDE Script created and working.
DONE Script created and working.
     cost=$0.1563 duration=10.5s
```

Use `--raw` for the full stream-json output. Use `-f` / `--follow` to tail in real-time.

### Messaging System

The container includes a file-based message bus for structured communication between the inner and outer Claude. Messages are timestamped JSON files in well-known directories:

```
/home/trustycage/.cage/
  outbox/           # Inner Claude writes here, outer reads
  inbox/            # Outer Claude writes here, inner reads
  cursor/           # Tracks read position (Kafka-like offset)
```

**Message types:**

| Type | Direction | Purpose |
|---|---|---|
| `task_complete` | inner -> outer | Signal task is done (includes summary) |
| `progress_update` | inner -> outer | Report what's being worked on |
| `info_request` | inner -> outer | Ask for files/data from the host |
| `error` | inner -> outer | Report a blocker |
| `info_response` | outer -> inner | Respond to an info_request |
| `ack` | outer -> inner | Acknowledge receipt of a message |

**Message format:**

```json
{
  "id": "msg-20260326T143000-a1b2",
  "type": "task_complete",
  "timestamp": "2026-03-26T14:30:00.000Z",
  "payload": { "summary": "Implemented feature X", "exit_code": 0 },
  "version": 1
}
```

The messaging system is initialized automatically during `tc create`. It enables the [cage-orchestrator](https://github.com/areese801/agent_skills) skill to dispatch tasks, monitor progress, handle information requests, and export results — keeping the human in the loop for sensitive operations (auth, git push, file access) while the inner Claude works autonomously.

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

- Docker (Docker Desktop, OrbStack, or Docker Engine)
- Python 3.11+
- Git
- rsync (pre-installed on macOS and most Linux distros; used by `export`)

## Development

```bash
git clone https://github.com/areese801/trusty-cage.git
cd trusty-cage
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Available make targets
make help
```

## License

MIT
