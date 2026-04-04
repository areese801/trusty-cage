"""
CLI entry point for trusty-cage.
"""

import importlib.resources
import io
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Optional

import typer
from rich import print as rprint
from rich.prompt import Confirm
from rich.table import Table

from trusty_cage import __version__, constants
from trusty_cage.auth import (
    copy_subscription_credentials,
    get_auth_exec_env,
    inject_api_key,
    prompt_auth_mode,
    validate_subscription_credentials,
)
from trusty_cage.config import resolve
from trusty_cage.docker import (
    container_create,
    container_exec,
    container_exists,
    container_is_running,
    container_recreate,
    container_remove,
    container_start,
    container_stop,
    copy_from_container,
    copy_to_container,
    exec_replace,
    is_docker_running,
    volume_create,
    volume_exists,
    volume_remove,
)
from trusty_cage.dotfiles import apply_dotfiles
from trusty_cage.environment import (
    AdditionalDir,
    create_meta,
    derive_name,
    derive_name_from_path,
    env_exists,
    get_env_dir,
    list_envs as get_all_envs,
    load_meta,
    save_meta,
)
from trusty_cage.image import build_if_needed, rebuild, resolve_dockerfile
from trusty_cage.messaging import (
    init_messaging_dirs,
    read_outbox,
    send_to_inbox,
    set_cursor,
)
from trusty_cage.network import apply_network_policy
from trusty_cage.stats import compute_stats, render_stats_table
from trusty_cage.version_check import check_for_updates

app = typer.Typer(
    name="trusty-cage",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        print(f"trusty-cage {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """
    Isolated Docker-based development environments for AI coding agents.
    """


def _require_docker() -> None:
    """
    Exit with error if Docker is not running.
    """
    if not is_docker_running():
        rprint("[bold red]Error: Docker is not running.[/bold red]")
        raise typer.Exit(1)


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing .env file"),
) -> None:
    """
    Initialize trusty-cage config directory and default .env file.
    """
    config_dir = constants.TRUSTY_CAGE_DIR
    env_path = constants.DOTENV_PATH

    config_dir.mkdir(parents=True, exist_ok=True)

    if env_path.exists() and not force:
        rprint(f"[dim]{env_path} already exists. Use --force to overwrite.[/dim]")
        return

    assets = importlib.resources.files("trusty_cage.assets")
    template = assets.joinpath("env.template").read_text()
    env_path.write_text(template)

    rprint(f"[bold green]Created {env_path}[/bold green]")
    rprint("[dim]Edit it to set your dotfiles repo, Python version, etc.[/dim]")


@app.command()
def create(
    git_repo_url: Optional[str] = typer.Argument(
        None, help="URL of the git repository to clone"
    ),
    name: Optional[str] = typer.Option(
        None, help="Override the derived environment name"
    ),
    dir_path: Optional[str] = typer.Option(
        None, "--dir", help="Create from a local directory instead of cloning a URL"
    ),
    no_attach: bool = typer.Option(
        False, "--no-attach", help="Create without attaching"
    ),
    auth_mode: Optional[str] = typer.Option(
        None, "--auth-mode", help="Authentication mode: api_key or subscription"
    ),
    dockerfile: Optional[str] = typer.Option(
        None,
        "--dockerfile",
        help="Path to a custom Dockerfile (replaces the default image)",
    ),
    add_dirs: Optional[list[str]] = typer.Option(
        None, "--add-dir", help="Additional local directories to include (repeatable)"
    ),
) -> None:
    """
    Create a new isolated development environment from a git repo or local directory.
    """
    _require_docker()
    check_for_updates()

    # Validate: exactly one source
    if git_repo_url and dir_path:
        rprint(
            "[bold red]Error: Provide either a git repo URL or --dir, not both.[/bold red]"
        )
        raise typer.Exit(1)
    if not git_repo_url and not dir_path:
        rprint("[bold red]Error: Provide a git repo URL or --dir <path>.[/bold red]")
        raise typer.Exit(1)

    # Resolve and validate --dir
    source_dir: Optional[Path] = None
    if dir_path:
        source_dir = Path(dir_path).resolve()
        if not source_dir.is_dir():
            rprint(
                f"[bold red]Error: Directory does not exist: {source_dir}[/bold red]"
            )
            raise typer.Exit(1)

    # Derive or validate name (always lowercase for Docker compatibility)
    if name:
        env_name = name.lower()
    elif git_repo_url:
        env_name = derive_name(git_repo_url)
    else:
        env_name = derive_name_from_path(str(source_dir))

    if env_exists(env_name):
        rprint(f"[bold red]Error: Environment '{env_name}' already exists.[/bold red]")
        raise typer.Exit(1)

    # Clean up ALL orphaned artifacts from a previous destroy.
    # tc destroy removes container + volume + meta.json but preserves the host
    # clone directory (so the user can grab exported work). If they then re-create
    # with the same name, we must wipe the stale env dir — otherwise the old host
    # clone files get copied into the fresh cage, producing "ghost work".
    env_dir = get_env_dir(env_name)
    if env_dir.exists():
        rprint(
            "[bold yellow]Warning: Cleaning up stale environment directory "
            "from a previous session.[/bold yellow]"
        )
        shutil.rmtree(env_dir)
    expected_container = f"{constants.CONTAINER_PREFIX}{env_name}"
    expected_volume = f"{constants.VOLUME_PREFIX}{env_name}"
    if container_exists(expected_container):
        rprint(
            f"[bold yellow]Warning: Removing orphaned container '{expected_container}' "
            f"from a previous environment.[/bold yellow]"
        )
        container_remove(expected_container, force=True)
    if volume_exists(expected_volume):
        rprint(
            f"[bold yellow]Warning: Removing orphaned volume '{expected_volume}' "
            f"from a previous environment.[/bold yellow]"
        )
        volume_remove(expected_volume)

    # Resolve auth mode: use flag if provided, otherwise prompt
    if auth_mode:
        if auth_mode not in constants.AUTH_MODES:
            rprint(
                f"[bold red]Error: Invalid auth mode '{auth_mode}'. "
                f"Must be one of: {', '.join(constants.AUTH_MODES)}[/bold red]"
            )
            raise typer.Exit(1)
    else:
        default_auth = resolve(constants.ENV_DEFAULT_AUTH_MODE)
        auth_mode = prompt_auth_mode(default=default_auth)

    if auth_mode == "subscription" and not validate_subscription_credentials():
        rprint(
            "[bold red]Error: ~/.claude/ not found. Cannot use subscription mode.[/bold red]"
        )
        raise typer.Exit(1)

    # Resolve Dockerfile and build image if needed
    python_version = resolve(constants.ENV_PYTHON_VERSION)
    dockerfile_path, is_custom = resolve_dockerfile(dockerfile)
    build_if_needed(
        python_version=python_version,
        dockerfile_path=dockerfile_path,
        is_custom=is_custom,
    )

    # Set up host clone directory
    env_dir = get_env_dir(env_name)
    env_dir.mkdir(parents=True, exist_ok=True)
    host_clone = env_dir / "repo"

    if host_clone.exists() and any(host_clone.iterdir()):
        rprint(f"[dim]Reusing existing host clone at {host_clone}[/dim]")
    elif git_repo_url:
        rprint(f"[bold blue]Cloning {git_repo_url}...[/bold blue]")
        try:
            subprocess.run(
                ["git", "clone", git_repo_url, str(host_clone)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            rprint(f"[bold red]Git clone failed: {e.stderr.strip()}[/bold red]")
            raise typer.Exit(1)
    else:
        rprint(f"[bold blue]Copying {source_dir} to host clone...[/bold blue]")
        subprocess.run(
            [
                "rsync",
                "-a",
                "--exclude",
                ".git/",
                "--exclude",
                "venv/",
                "--exclude",
                ".venv/",
                "--exclude",
                "__pycache__/",
                str(source_dir) + "/",
                str(host_clone) + "/",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    # Write meta.json
    repo_url = git_repo_url or ""
    meta = create_meta(
        name=env_name,
        repo_url=repo_url,
        auth_mode=auth_mode,
    )

    # Create volume and container
    volume_create(meta.volume_name)
    rprint(f"[dim]Created volume {meta.volume_name}[/dim]")

    # Build volume mounts list (including --add-dir volumes)
    volume_mounts = [f"{meta.volume_name}:{constants.CONTAINER_PROJECT_DIR}"]
    add_dir_specs: list[
        tuple[str, str, str, Path]
    ] = []  # (ad_name, vol, cpath, source)
    if add_dirs:
        for add_dir_path in add_dirs:
            add_source = Path(add_dir_path).resolve()
            if not add_source.is_dir():
                rprint(
                    f"[bold red]Error: Directory does not exist: {add_source}[/bold red]"
                )
                raise typer.Exit(1)
            ad_name = derive_name_from_path(str(add_source))
            if ad_name == "project":
                rprint(
                    "[bold red]Error: Cannot use name 'project' — reserved.[/bold red]"
                )
                raise typer.Exit(1)
            vol_name = f"{constants.VOLUME_PREFIX}{env_name}-{ad_name}"
            container_path = f"{constants.CONTAINER_HOME}/{ad_name}"
            volume_create(vol_name)
            volume_mounts.append(f"{vol_name}:{container_path}")
            add_dir_specs.append((ad_name, vol_name, container_path, add_source))

    container_create(
        name=meta.container_name,
        image=constants.IMAGE_TAG,
        volume_mounts=volume_mounts,
        hostname=env_name,
        cap_add=["NET_ADMIN"],
    )
    container_start(meta.container_name)
    rprint(f"[dim]Created and started container {meta.container_name}[/dim]")

    # Copy repo files (excluding .git/) into container
    with tempfile.TemporaryDirectory(prefix="trusty-cage-repo-") as tmpdir:
        # Copy repo contents minus .git/ to a staging dir
        staging = Path(tmpdir) / "staging"
        staging.mkdir()

        for item in host_clone.iterdir():
            if item.name == ".git":
                continue
            dest = staging / item.name
            if item.is_dir():
                shutil.copytree(item, dest, symlinks=True)
            else:
                shutil.copy2(item, dest)

        copy_to_container(
            str(staging) + "/.",
            meta.container_name,
            constants.CONTAINER_PROJECT_DIR,
        )

    # chown project dir
    container_exec(
        meta.container_name,
        [
            "chown",
            "-R",
            f"{constants.CONTAINER_USER}:{constants.CONTAINER_USER}",
            constants.CONTAINER_PROJECT_DIR,
        ],
        user="root",
    )

    # Create messaging directories for cage orchestrator communication
    init_messaging_dirs(meta.container_name)

    # Init local git inside container (no remotes)
    container_exec(
        meta.container_name,
        ["git", "config", "--global", "user.name", "trusty-cage"],
        user=constants.CONTAINER_USER,
    )
    container_exec(
        meta.container_name,
        ["git", "config", "--global", "user.email", "trusty-cage@localhost"],
        user=constants.CONTAINER_USER,
    )
    container_exec(
        meta.container_name,
        ["git", "init", "-b", "main"],
        user=constants.CONTAINER_USER,
    )
    container_exec(
        meta.container_name,
        ["git", "add", "."],
        user=constants.CONTAINER_USER,
    )
    container_exec(
        meta.container_name,
        ["git", "commit", "-m", "Initial commit (trusty-cage import)"],
        user=constants.CONTAINER_USER,
    )
    rprint("[dim]Initialized local git repo inside container.[/dim]")

    # Apply dotfiles
    dotfiles_repo = resolve(constants.ENV_DOTFILES_REPO)
    if dotfiles_repo:
        apply_dotfiles(meta.container_name, dotfiles_repo)

    # Copy subscription credentials if needed
    if auth_mode == "subscription":
        copy_subscription_credentials(meta.container_name)
        rprint("[dim]Copied subscription credentials into container.[/dim]")

    # Add additional directories if specified
    if add_dir_specs:
        for ad_name, vol_name, container_path, add_source in add_dir_specs:
            # Host clone
            dirs_parent = env_dir / "dirs"
            dirs_parent.mkdir(parents=True, exist_ok=True)
            host_clone_dir = dirs_parent / ad_name
            subprocess.run(
                [
                    "rsync",
                    "-a",
                    "--exclude",
                    ".git/",
                    str(add_source) + "/",
                    str(host_clone_dir) + "/",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            # Copy into container
            with tempfile.TemporaryDirectory(prefix="trusty-cage-adddir-") as td:
                staging = Path(td) / "staging"
                staging.mkdir()
                for item in host_clone_dir.iterdir():
                    if item.name == ".git":
                        continue
                    dest = staging / item.name
                    if item.is_dir():
                        shutil.copytree(item, dest, symlinks=True)
                    else:
                        shutil.copy2(item, dest)
                copy_to_container(
                    str(staging) + "/.",
                    meta.container_name,
                    container_path,
                )

            container_exec(
                meta.container_name,
                [
                    "chown",
                    "-R",
                    f"{constants.CONTAINER_USER}:{constants.CONTAINER_USER}",
                    container_path,
                ],
                user="root",
            )
            container_exec(
                meta.container_name,
                [
                    "bash",
                    "-c",
                    f"cd {container_path} && git init -b main && git add . "
                    f"&& git commit -m 'Initial commit (trusty-cage import)'",
                ],
                user=constants.CONTAINER_USER,
            )

            dir_entry = AdditionalDir(
                name=ad_name,
                host_source_path=str(add_source),
                host_clone_path=str(host_clone_dir),
                volume_name=vol_name,
                container_path=container_path,
                added_at=datetime.now(timezone.utc).isoformat(),
            )
            meta.additional_dirs.append(dir_entry.to_dict())
            rprint(f"[dim]Added additional dir: {ad_name}[/dim]")

        save_meta(meta)

    rprint(f"[bold green]Environment '{env_name}' created successfully.[/bold green]")

    if not no_attach:
        attach(env_name)


@app.command()
def attach(
    name: str = typer.Argument(help="Name of the environment to attach to"),
) -> None:
    """
    Attach to an existing environment's interactive tmux session.
    """
    _require_docker()
    check_for_updates()

    if not env_exists(name):
        rprint(f"[bold red]Error: Environment '{name}' not found.[/bold red]")
        raise typer.Exit(1)

    meta = load_meta(name)

    # Start container if stopped
    if not container_is_running(meta.container_name):
        rprint(f"[dim]Starting container {meta.container_name}...[/dim]")
        container_start(meta.container_name)

    # Apply network policy
    apply_network_policy(meta.container_name)

    # Build env dict for API key injection
    exec_env: dict[str, str] = {}
    try:
        exec_env = get_auth_exec_env(meta)
    except ValueError:
        rprint(
            f"[bold yellow]Warning: {meta.api_key_env} is not set. "
            "Claude Code will not have an API key in this session.[/bold yellow]"
        )

    # Check if tmux session exists
    tmux_check = container_exec(
        meta.container_name,
        ["tmux", "has-session", "-t", constants.TMUX_SESSION],
        user=constants.CONTAINER_USER,
        env=exec_env,
        check=False,
    )

    if tmux_check.returncode != 0:
        # Append tmux prefix override (avoids conflict with host tmux)
        tmux_prefix = resolve(constants.ENV_TMUX_PREFIX)
        container_exec(
            meta.container_name,
            [
                "bash",
                "-c",
                f'echo "\n# trusty-cage: use a different prefix inside the container\n'
                f"# so it doesn't conflict with the host tmux prefix (Ctrl-b)\n"
                f"unbind C-b\nset -g prefix {tmux_prefix}\n"
                f'bind {tmux_prefix} send-prefix" '
                f">> {constants.CONTAINER_HOME}/.tmux.conf",
            ],
            user=constants.CONTAINER_USER,
        )

        # Create 3-pane layout: nvim (left 60%) | claude (top-right) | shell (bottom-right)
        sess = constants.TMUX_SESSION
        proj = constants.CONTAINER_PROJECT_DIR

        # New session — starts with one pane (will be nvim)
        container_exec(
            meta.container_name,
            ["tmux", "new-session", "-d", "-s", sess, "-c", proj],
            user=constants.CONTAINER_USER,
            env=exec_env,
        )

        # Query pane-base-index (user's tmux config may set it to 1)
        pbi_result = container_exec(
            meta.container_name,
            [
                "tmux",
                "show-options",
                "-gv",
                "pane-base-index",
            ],
            user=constants.CONTAINER_USER,
            env=exec_env,
            check=False,
        )
        pane_base = (
            int(pbi_result.stdout.strip())
            if pbi_result.returncode == 0 and pbi_result.stdout.strip().isdigit()
            else 0
        )
        left_pane = pane_base
        top_right = pane_base + 1

        # Split horizontally: left (nvim) | right
        container_exec(
            meta.container_name,
            ["tmux", "split-window", "-h", "-t", sess, "-c", proj],
            user=constants.CONTAINER_USER,
            env=exec_env,
        )
        # Split right pane vertically: top-right (claude) | bottom-right (shell)
        container_exec(
            meta.container_name,
            ["tmux", "split-window", "-v", "-t", sess, "-c", proj],
            user=constants.CONTAINER_USER,
            env=exec_env,
        )
        # Resize left pane to 60%
        container_exec(
            meta.container_name,
            ["tmux", "resize-pane", "-t", f"{sess}:.{left_pane}", "-x", "60%"],
            user=constants.CONTAINER_USER,
            env=exec_env,
        )

        # Left pane: nvim
        container_exec(
            meta.container_name,
            ["tmux", "send-keys", "-t", f"{sess}:.{left_pane}", "nvim", "Enter"],
            user=constants.CONTAINER_USER,
            env=exec_env,
        )
        # Top-right pane: claude
        container_exec(
            meta.container_name,
            [
                "tmux",
                "send-keys",
                "-t",
                f"{sess}:.{top_right}",
                "claude --dangerously-skip-permissions",
                "Enter",
            ],
            user=constants.CONTAINER_USER,
            env=exec_env,
        )

        # Focus on claude pane (top-right)
        container_exec(
            meta.container_name,
            ["tmux", "select-pane", "-t", f"{sess}:.{top_right}"],
            user=constants.CONTAINER_USER,
            env=exec_env,
        )
        rprint("[dim]Created tmux session with 3 panes (editor, claude, shell).[/dim]")

    rprint(f"[bold green]Attaching to '{name}'...[/bold green]")

    # Replace process with docker exec into tmux
    exec_replace(
        meta.container_name,
        ["tmux", "attach-session", "-t", constants.TMUX_SESSION],
        env=exec_env,
    )


@app.command()
def stop(
    name: str = typer.Argument(help="Name of the environment to stop"),
) -> None:
    """
    Stop an environment's container (preserves volume).
    """
    _require_docker()

    if not env_exists(name):
        rprint(f"[bold red]Error: Environment '{name}' not found.[/bold red]")
        raise typer.Exit(1)

    meta = load_meta(name)

    if not container_is_running(meta.container_name):
        rprint(f"[dim]Container '{meta.container_name}' is already stopped.[/dim]")
        return

    container_stop(meta.container_name)
    rprint(f"[bold green]Stopped '{name}'.[/bold green]")


@app.command("list")
def list_envs(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    List all environments with status, creation date, and repo URL.
    """
    envs = get_all_envs()

    def _resolve_status(meta_item) -> str:
        """
        Determine environment status: running, stopped, or orphaned.
        """
        try:
            if not container_exists(meta_item.container_name):
                return "orphaned"
            if container_is_running(meta_item.container_name):
                return "running"
            return "stopped"
        except Exception:
            return "unknown"

    if json_output:
        if not envs:
            print("[]")
            return

        entries = []
        for meta in envs:
            created = (
                meta.created_at[:10] if len(meta.created_at) >= 10 else meta.created_at
            )
            entries.append(
                {
                    "name": meta.name,
                    "status": _resolve_status(meta),
                    "repo_url": meta.repo_url,
                    "created_at": created,
                    "auth_mode": meta.auth_mode,
                    "additional_dirs": [d["name"] for d in meta.additional_dirs],
                }
            )

        print(json.dumps(entries, indent=2))
        return

    if not envs:
        rprint("[dim]No environments found.[/dim]")
        return

    table = Table(title="trusty-cage environments")
    table.add_column("Name", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Repo", style="dim")
    table.add_column("Created", style="dim")
    table.add_column("Auth", style="dim")
    table.add_column("Dirs", style="dim")

    status_styles = {
        "running": "[green]running[/green]",
        "stopped": "[yellow]stopped[/yellow]",
        "orphaned": "[red]orphaned[/red]",
        "unknown": "[red]unknown[/red]",
    }

    for meta in envs:
        status = _resolve_status(meta)
        created = (
            meta.created_at[:10] if len(meta.created_at) >= 10 else meta.created_at
        )
        dirs_str = (
            ", ".join(d["name"] for d in meta.additional_dirs)
            if meta.additional_dirs
            else ""
        )
        table.add_row(
            meta.name,
            status_styles.get(status, status),
            meta.repo_url or "(local)",
            created,
            meta.auth_mode,
            dirs_str,
        )

    rprint(table)


@app.command()
def exists(
    name: str = typer.Argument(help="Name of the environment to check"),
) -> None:
    """
    Check if an environment exists. Exit code 0 if yes, 1 if no.
    """
    if env_exists(name):
        raise typer.Exit(0)
    else:
        raise typer.Exit(1)


def _ensure_git_config(container_name: str) -> None:
    """
    Ensure git user config exists inside the container.

    This is needed after container recreation since ~/.gitconfig lives in
    the container filesystem (not a volume) and gets lost on rm/create.
    """
    container_exec(
        container_name,
        ["git", "config", "--global", "user.name", "trusty-cage"],
        user=constants.CONTAINER_USER,
    )
    container_exec(
        container_name,
        ["git", "config", "--global", "user.email", "trusty-cage@localhost"],
        user=constants.CONTAINER_USER,
    )


def _build_volume_mounts(meta) -> list[str]:
    """
    Build the full list of volume mounts for a cage from its MetaJson.
    """
    mounts = [f"{meta.volume_name}:{constants.CONTAINER_PROJECT_DIR}"]
    for d in meta.additional_dirs:
        mounts.append(f"{d['volume_name']}:{d['container_path']}")
    return mounts


@app.command("add-dir")
def add_dir(
    name: str = typer.Argument(help="Name of the cage environment"),
    dir_path: str = typer.Argument(help="Path to the local directory to add"),
    dir_name: Optional[str] = typer.Option(
        None, "--name", help="Override the derived directory name"
    ),
) -> None:
    """
    Add a local directory to an existing cage environment.
    """
    _require_docker()

    if not env_exists(name):
        rprint(f"[bold red]Error: Environment '{name}' not found.[/bold red]")
        raise typer.Exit(1)

    meta = load_meta(name)

    # Resolve and validate source directory
    source = Path(dir_path).resolve()
    if not source.is_dir():
        rprint(f"[bold red]Error: Directory does not exist: {source}[/bold red]")
        raise typer.Exit(1)

    # Derive or validate name
    derived_name = dir_name or derive_name_from_path(str(source))

    if derived_name == "project":
        rprint(
            "[bold red]Error: Cannot use name 'project' — reserved for main project.[/bold red]"
        )
        raise typer.Exit(1)

    # Check for name collision with existing additional dirs
    if meta.get_additional_dir(derived_name) is not None:
        rprint(
            f"[bold red]Error: Additional dir '{derived_name}' already exists "
            f"in cage '{name}'.[/bold red]"
        )
        raise typer.Exit(1)

    # Show derived name if it differs from basename (sanitization)
    if derived_name != source.name.lower():
        rprint(f"[dim]Derived name: {derived_name} (from {source.name})[/dim]")

    # Create volume
    vol_name = f"{constants.VOLUME_PREFIX}{name}-{derived_name}"
    if not volume_exists(vol_name):
        volume_create(vol_name)
    rprint(f"[dim]Created volume {vol_name}[/dim]")

    # Copy source to host clone
    env_dir = get_env_dir(name)
    dirs_parent = env_dir / "dirs"
    dirs_parent.mkdir(parents=True, exist_ok=True)
    host_clone = dirs_parent / derived_name

    subprocess.run(
        [
            "rsync",
            "-a",
            "--exclude",
            ".git/",
            str(source) + "/",
            str(host_clone) + "/",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    # Build full volume mounts list including the new dir
    container_path = f"{constants.CONTAINER_HOME}/{derived_name}"
    all_mounts = _build_volume_mounts(meta)
    all_mounts.append(f"{vol_name}:{container_path}")

    # Recreate container with new mount
    rprint("[dim]Recreating container with new volume mount...[/dim]")
    container_recreate(
        name=meta.container_name,
        image=constants.IMAGE_TAG,
        volume_mounts=all_mounts,
        hostname=meta.name,
        cap_add=["NET_ADMIN"],
    )
    _ensure_git_config(meta.container_name)

    # Copy files into container
    with tempfile.TemporaryDirectory(prefix="trusty-cage-adddir-") as tmpdir:
        staging = Path(tmpdir) / "staging"
        staging.mkdir()
        for item in host_clone.iterdir():
            if item.name == ".git":
                continue
            dest = staging / item.name
            if item.is_dir():
                shutil.copytree(item, dest, symlinks=True)
            else:
                shutil.copy2(item, dest)

        copy_to_container(
            str(staging) + "/.",
            meta.container_name,
            container_path,
        )

    # chown
    container_exec(
        meta.container_name,
        [
            "chown",
            "-R",
            f"{constants.CONTAINER_USER}:{constants.CONTAINER_USER}",
            container_path,
        ],
        user="root",
    )

    # git init inside the new dir
    container_exec(
        meta.container_name,
        [
            "bash",
            "-c",
            f"cd {container_path} && git init -b main && git add . "
            f"&& git commit -m 'Initial commit (trusty-cage import)'",
        ],
        user=constants.CONTAINER_USER,
    )

    # Update meta.json
    dir_entry = AdditionalDir(
        name=derived_name,
        host_source_path=str(source),
        host_clone_path=str(host_clone),
        volume_name=vol_name,
        container_path=container_path,
        added_at=datetime.now(timezone.utc).isoformat(),
    )
    meta.additional_dirs.append(dir_entry.to_dict())
    save_meta(meta)

    rprint(f"[bold green]Added '{derived_name}' to cage '{name}'.[/bold green]")
    rprint(f"[dim]Container path: {container_path}[/dim]")


@app.command("remove-dir")
def remove_dir(
    name: str = typer.Argument(help="Name of the cage environment"),
    dir_name: str = typer.Argument(help="Name of the additional directory to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """
    Remove an additional directory from a cage environment.
    """
    _require_docker()

    if not env_exists(name):
        rprint(f"[bold red]Error: Environment '{name}' not found.[/bold red]")
        raise typer.Exit(1)

    meta = load_meta(name)

    # Find the dir entry
    dir_entry = meta.get_additional_dir(dir_name)
    if dir_entry is None:
        rprint(
            f"[bold red]Error: Additional dir '{dir_name}' not found "
            f"in cage '{name}'.[/bold red]"
        )
        raise typer.Exit(1)

    if not yes and not Confirm.ask(
        f"Remove '{dir_name}' from cage '{name}'? Volume and host clone will be deleted."
    ):
        rprint("[dim]Cancelled.[/dim]")
        return

    # Rebuild volume mounts list without the removed dir
    meta.additional_dirs = [d for d in meta.additional_dirs if d["name"] != dir_name]
    all_mounts = _build_volume_mounts(meta)

    # Recreate container without the removed mount
    rprint("[dim]Recreating container without removed volume mount...[/dim]")
    container_recreate(
        name=meta.container_name,
        image=constants.IMAGE_TAG,
        volume_mounts=all_mounts,
        hostname=meta.name,
        cap_add=["NET_ADMIN"],
    )
    _ensure_git_config(meta.container_name)

    # Remove volume
    if volume_exists(dir_entry.volume_name):
        volume_remove(dir_entry.volume_name)
        rprint(f"[dim]Removed volume {dir_entry.volume_name}[/dim]")

    # Remove host clone
    host_clone = Path(dir_entry.host_clone_path)
    if host_clone.exists():
        shutil.rmtree(host_clone)

    # Update meta.json
    save_meta(meta)

    rprint(f"[bold green]Removed '{dir_name}' from cage '{name}'.[/bold green]")


def _collect_exclude_patterns(
    target: Path,
    protect: list[str] | None = None,
) -> list[str]:
    """
    Build a deduplicated list of rsync --exclude patterns from .git/,
    .cageprotect, venv/, and explicit --protect globs. Also reads patterns
    from the target's .gitignore and .cageprotect files.

    Note: .gitignore itself is NOT excluded — cage-side changes to .gitignore
    will transfer to the host. Users who want to preserve the host's .gitignore
    should list it in .cageprotect.
    """
    seen: set[str] = set()
    patterns: list[str] = []

    def _add(pat: str) -> None:
        if pat not in seen:
            seen.add(pat)
            patterns.append(pat)

    _add(".git/")
    _add(".cageprotect")
    _add("venv/")
    _add(".venv/")

    for filename in (".gitignore", ".cageprotect"):
        path = target / filename
        if path.is_file():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    _add(line)

    for pat in protect or []:
        _add(pat)

    return patterns


def _export_to_tempdir(
    container_name: str, tmpdir: Path, container_path: str | None = None
) -> Path:
    """
    Copy a container directory into a temp dir and strip .git/.
    Returns the path to the exported directory.
    """
    src_path = container_path or constants.CONTAINER_PROJECT_DIR
    export_dir = tmpdir / "export"
    copy_from_container(
        container_name,
        src_path + "/.",
        str(export_dir),
    )
    exported_git = export_dir / ".git"
    if exported_git.exists():
        shutil.rmtree(exported_git)
    return export_dir


@app.command()
def export(
    name: str = typer.Argument(help="Name of the environment to export"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    output_dir: Optional[str] = typer.Option(
        None,
        "--output-dir",
        help="Export to this directory instead of the default host clone",
    ),
    delete: bool = typer.Option(
        False, "--delete", help="Delete host files not present in container"
    ),
    protect: Optional[list[str]] = typer.Option(
        None,
        "--protect",
        help="Glob patterns to exclude from sync (repeatable)",
    ),
    target_dirs: Optional[list[str]] = typer.Option(
        None,
        "--dir",
        help="Export specific additional dir(s) instead of main project (repeatable)",
    ),
    all_dirs: bool = typer.Option(
        False, "--all", help="Export main project and all additional dirs"
    ),
    stats: bool = typer.Option(
        False, "--stats", help="Show language-aware code statistics after export"
    ),
) -> None:
    """
    Export work from container back to host clone.
    """
    _require_docker()

    if not env_exists(name):
        rprint(f"[bold red]Error: Environment '{name}' not found.[/bold red]")
        raise typer.Exit(1)

    meta = load_meta(name)

    # Build list of (container_path, host_target, label) tuples to export
    export_targets: list[tuple[str, Path, str]] = []

    if all_dirs:
        main_target = (
            Path(output_dir).resolve() if output_dir else Path(meta.host_clone_path)
        )
        export_targets.append((constants.CONTAINER_PROJECT_DIR, main_target, "project"))
        for d in meta.additional_dirs:
            export_targets.append(
                (d["container_path"], Path(d["host_clone_path"]), d["name"])
            )
    elif target_dirs:
        for td_name in target_dirs:
            dir_entry = meta.get_additional_dir(td_name)
            if dir_entry is None:
                rprint(
                    f"[bold red]Error: Additional dir '{td_name}' not found.[/bold red]"
                )
                raise typer.Exit(1)
            export_targets.append(
                (
                    dir_entry.container_path,
                    Path(dir_entry.host_clone_path),
                    dir_entry.name,
                )
            )
    else:
        main_target = (
            Path(output_dir).resolve() if output_dir else Path(meta.host_clone_path)
        )
        if output_dir and not main_target.is_dir():
            rprint(
                f"[bold red]Error: Output directory does not exist: {main_target}[/bold red]"
            )
            raise typer.Exit(1)
        export_targets.append((constants.CONTAINER_PROJECT_DIR, main_target, "project"))

    if not yes and not Confirm.ask(
        f"Export {len(export_targets)} target(s) from cage '{name}'?"
    ):
        rprint("[dim]Cancelled.[/dim]")
        return

    # Ensure container is running for docker cp
    was_stopped = False
    if not container_is_running(meta.container_name):
        container_start(meta.container_name)
        was_stopped = True

    for container_path, host_target, label in export_targets:
        if len(export_targets) > 1:
            rprint(f"\n[bold blue]Exporting {label}...[/bold blue]")

        with tempfile.TemporaryDirectory(prefix="trusty-cage-export-") as tmpdir:
            export_dir = _export_to_tempdir(
                meta.container_name, Path(tmpdir), container_path
            )

            # Compute stats before rsync overwrites the host
            stat_results = None
            if stats:
                stat_results, used_cloc = compute_stats(
                    before=host_target, after=export_dir
                )

            rsync_cmd = ["rsync", "-a"]
            if delete:
                rsync_cmd.append("--delete")
            for pat in _collect_exclude_patterns(host_target, protect):
                rsync_cmd.extend(["--exclude", pat])
            rsync_cmd.extend(
                [
                    str(export_dir) + "/",
                    str(host_target) + "/",
                ]
            )

            subprocess.run(
                rsync_cmd,
                check=True,
                capture_output=True,
                text=True,
            )

            if stat_results:
                render_stats_table(stat_results, used_cloc)

        rprint(f"[bold green]Exported {label} to {host_target}[/bold green]")

    if was_stopped:
        container_stop(meta.container_name)

    if not target_dirs and not all_dirs:
        main_target = export_targets[0][1]
        rprint("[dim]Suggested workflow:[/dim]")
        rprint(f"  cd {main_target}")
        rprint("  git diff")
        rprint("  git add -A && git commit -m 'work from trusty-cage'")
        if meta.repo_url:
            rprint("  git push")


def _diff_one(
    container_name: str,
    container_path: str,
    target: Path,
    label: str,
    full: bool,
    stats: bool = False,
) -> None:
    """
    Show diff for one container directory against its host clone.
    """
    with tempfile.TemporaryDirectory(prefix="trusty-cage-diff-") as tmpdir:
        export_dir = _export_to_tempdir(container_name, Path(tmpdir), container_path)

        rsync_cmd = ["rsync", "-a", "--dry-run", "-i", "--delete"]
        for pat in _collect_exclude_patterns(target):
            rsync_cmd.extend(["--exclude", pat])
        rsync_cmd.extend([str(export_dir) + "/", str(target) + "/"])

        result = subprocess.run(rsync_cmd, capture_output=True, text=True, check=True)

        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]

        if not lines:
            rprint(f"[dim]No differences ({label}).[/dim]")
            return

        changes: list[tuple[str, str]] = []
        for ln in lines:
            if ln.startswith("*deleting"):
                filename = ln.split(None, 1)[1].strip()
                changes.append((filename, "deleted"))
            elif ln[0:1] in (">", "<", "c"):
                parts = ln.split(None, 1)
                if len(parts) < 2:
                    continue
                code, filename = parts[0], parts[1].strip()
                if not filename or filename.endswith("/"):
                    continue
                if "+" * 4 in code:
                    changes.append((filename, "added"))
                else:
                    changes.append((filename, "modified"))

        if not changes:
            rprint(f"[dim]No differences ({label}).[/dim]")
            return

        if full:
            for filename, status in changes:
                cage_file = export_dir / filename
                host_file = target / filename
                if status == "deleted":
                    rprint(f"\n[bold red]--- deleted: {filename}[/bold red]")
                    continue
                diff_result = subprocess.run(
                    ["diff", "-u", str(host_file), str(cage_file)],
                    capture_output=True,
                    text=True,
                )
                if diff_result.stdout:
                    rprint(f"\n[bold]{filename}[/bold]")
                    rprint(diff_result.stdout.rstrip())
                elif status == "added":
                    rprint(f"\n[bold green]+++ added: {filename}[/bold green]")
                    rprint(cage_file.read_text().rstrip())
        else:
            table = Table(show_header=True, header_style="bold")
            table.add_column("File")
            table.add_column("Status")
            style_map = {
                "added": "green",
                "modified": "yellow",
                "deleted": "red",
            }
            for filename, status in changes:
                table.add_row(
                    filename,
                    f"[{style_map[status]}]{status}[/{style_map[status]}]",
                )
            rprint(table)
            rprint(f"[dim]{len(changes)} file(s) changed ({label})[/dim]")

        if stats and changes:
            stat_results, used_cloc = compute_stats(before=target, after=export_dir)
            render_stats_table(stat_results, used_cloc)


@app.command()
def diff(
    name: str = typer.Argument(help="Name of the environment"),
    full: bool = typer.Option(False, "--full", help="Show full diff content"),
    output_dir: Optional[str] = typer.Option(
        None,
        "--output-dir",
        help="Compare against this directory instead of the default host clone",
    ),
    target_dirs: Optional[list[str]] = typer.Option(
        None,
        "--dir",
        help="Diff specific additional dir(s) instead of main project (repeatable)",
    ),
    all_dirs: bool = typer.Option(
        False, "--all", help="Diff main project and all additional dirs"
    ),
    stats: bool = typer.Option(
        False, "--stats", help="Show language-aware code statistics"
    ),
) -> None:
    """
    Preview what 'tc export' would change (dry run).
    """
    _require_docker()

    if not env_exists(name):
        rprint(f"[bold red]Error: Environment '{name}' not found.[/bold red]")
        raise typer.Exit(1)

    meta = load_meta(name)

    # Build list of (container_path, host_target, label) tuples
    diff_targets: list[tuple[str, Path, str]] = []

    if all_dirs:
        main_target = (
            Path(output_dir).resolve() if output_dir else Path(meta.host_clone_path)
        )
        diff_targets.append((constants.CONTAINER_PROJECT_DIR, main_target, "project"))
        for d in meta.additional_dirs:
            diff_targets.append(
                (d["container_path"], Path(d["host_clone_path"]), d["name"])
            )
    elif target_dirs:
        for td_name in target_dirs:
            dir_entry = meta.get_additional_dir(td_name)
            if dir_entry is None:
                rprint(
                    f"[bold red]Error: Additional dir '{td_name}' not found.[/bold red]"
                )
                raise typer.Exit(1)
            diff_targets.append(
                (
                    dir_entry.container_path,
                    Path(dir_entry.host_clone_path),
                    dir_entry.name,
                )
            )
    else:
        if output_dir:
            target = Path(output_dir).resolve()
            if not target.is_dir():
                rprint(
                    f"[bold red]Error: Directory does not exist: {target}[/bold red]"
                )
                raise typer.Exit(1)
        else:
            target = Path(meta.host_clone_path)
        diff_targets.append((constants.CONTAINER_PROJECT_DIR, target, "project"))

    was_stopped = False
    if not container_is_running(meta.container_name):
        container_start(meta.container_name)
        was_stopped = True

    try:
        for container_path, host_target, label in diff_targets:
            if len(diff_targets) > 1:
                rprint(f"\n[bold blue]Diff: {label}[/bold blue]")
            _diff_one(
                meta.container_name, container_path, host_target, label, full, stats
            )
    finally:
        if was_stopped:
            container_stop(meta.container_name)


def _sync_one(
    meta,
    source: Path,
    container_dest: str,
    label: str,
    files: list[str] | None = None,
) -> None:
    """
    Sync a single host directory into the container.
    """
    with tempfile.TemporaryDirectory(prefix="trusty-cage-sync-") as tmpdir:
        stage_dir = Path(tmpdir) / "staging"

        if files:
            for relpath in files:
                src_file = source / relpath
                if not src_file.is_file():
                    rprint(f"[bold red]Error: File not found: {relpath}[/bold red]")
                    raise typer.Exit(1)
                dest_file = stage_dir / relpath
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dest_file)
        else:
            rsync_cmd = ["rsync", "-a"]
            for pat in _collect_exclude_patterns(source):
                rsync_cmd.extend(["--exclude", pat])
            rsync_cmd.extend([str(source) + "/", str(stage_dir) + "/"])
            subprocess.run(rsync_cmd, check=True, capture_output=True, text=True)

        copy_to_container(
            str(stage_dir) + "/.",
            meta.container_name,
            container_dest,
        )

        container_exec(
            meta.container_name,
            [
                "chown",
                "-R",
                f"{constants.CONTAINER_USER}:{constants.CONTAINER_USER}",
                container_dest,
            ],
            user="root",
        )

    file_desc = f"{len(files)} file(s)" if files else "all files"
    rprint(
        f"[bold green]Synced {file_desc} ({label}) into cage '{meta.name}'[/bold green]"
    )


@app.command()
def sync(
    name: str = typer.Argument(help="Name of the environment to sync into"),
    files: Optional[list[str]] = typer.Option(
        None, "--files", help="Specific files to sync (relative to project root)"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    target_dirs: Optional[list[str]] = typer.Option(
        None,
        "--dir",
        help="Sync specific additional dir(s) instead of main project (repeatable)",
    ),
    all_dirs: bool = typer.Option(
        False, "--all", help="Sync main project and all additional dirs"
    ),
) -> None:
    """
    Push host files into a cage environment (inverse of export).
    """
    _require_docker()

    if not env_exists(name):
        rprint(f"[bold red]Error: Environment '{name}' not found.[/bold red]")
        raise typer.Exit(1)

    meta = load_meta(name)

    # Build list of (host_source, container_dest, label) tuples
    sync_targets: list[tuple[Path, str, str]] = []

    if all_dirs:
        sync_targets.append(
            (Path(meta.host_clone_path), constants.CONTAINER_PROJECT_DIR, "project")
        )
        for d in meta.additional_dirs:
            sync_targets.append(
                (Path(d["host_clone_path"]), d["container_path"], d["name"])
            )
    elif target_dirs:
        for td_name in target_dirs:
            dir_entry = meta.get_additional_dir(td_name)
            if dir_entry is None:
                rprint(
                    f"[bold red]Error: Additional dir '{td_name}' not found.[/bold red]"
                )
                raise typer.Exit(1)
            sync_targets.append(
                (
                    Path(dir_entry.host_clone_path),
                    dir_entry.container_path,
                    dir_entry.name,
                )
            )
    else:
        sync_targets.append(
            (Path(meta.host_clone_path), constants.CONTAINER_PROJECT_DIR, "project")
        )

    # Validate all sources exist
    for source, _, label in sync_targets:
        if not source.is_dir():
            rprint(f"[bold red]Error: Host clone not found: {source}[/bold red]")
            raise typer.Exit(1)

    if not yes and not Confirm.ask(
        f"Sync {len(sync_targets)} target(s) into cage '{name}'?"
    ):
        rprint("[dim]Cancelled.[/dim]")
        return

    was_stopped = False
    if not container_is_running(meta.container_name):
        container_start(meta.container_name)
        was_stopped = True

    try:
        for source, container_dest, label in sync_targets:
            if len(sync_targets) > 1:
                rprint(f"\n[bold blue]Syncing {label}...[/bold blue]")
            # --files only applies to main project (first target without --dir/--all)
            sync_files = files if (not target_dirs and not all_dirs) else None
            _sync_one(meta, source, container_dest, label, sync_files)
    finally:
        if was_stopped:
            container_stop(meta.container_name)


@app.command()
def destroy(
    name: str = typer.Argument(help="Name of the environment to destroy"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """
    Destroy an environment's container and volume (keeps host clone).
    """
    _require_docker()

    if not env_exists(name):
        rprint(f"[bold red]Error: Environment '{name}' not found.[/bold red]")
        raise typer.Exit(1)

    meta = load_meta(name)

    if not yes and not Confirm.ask(
        f"Destroy environment '{name}'? Container and volume will be removed."
    ):
        rprint("[dim]Cancelled.[/dim]")
        return

    # Remove container
    if container_exists(meta.container_name):
        container_remove(meta.container_name, force=True)
        rprint(f"[dim]Removed container {meta.container_name}[/dim]")

    # Remove main volume
    if volume_exists(meta.volume_name):
        volume_remove(meta.volume_name)
        rprint(f"[dim]Removed volume {meta.volume_name}[/dim]")

    # Remove additional dir volumes
    for d in meta.additional_dirs:
        if volume_exists(d["volume_name"]):
            volume_remove(d["volume_name"])
            rprint(f"[dim]Removed volume {d['volume_name']}[/dim]")

    # Remove dirs/ directory
    dirs_path = get_env_dir(name) / "dirs"
    if dirs_path.exists():
        shutil.rmtree(dirs_path)

    # Delete meta.json (keep repo/)
    meta_path = get_env_dir(name) / "meta.json"
    if meta_path.exists():
        meta_path.unlink()

    rprint(f"[bold green]Destroyed '{name}'.[/bold green]")
    rprint(f"[dim]Host clone preserved at {meta.host_clone_path}[/dim]")


@app.command("rebuild-image")
def rebuild_image(
    dockerfile: Optional[str] = typer.Option(
        None,
        "--dockerfile",
        help="Path to a custom Dockerfile (replaces the default image)",
    ),
) -> None:
    """
    Force rebuild the Docker image from scratch.
    """
    _require_docker()

    python_version = resolve(constants.ENV_PYTHON_VERSION)
    dockerfile_path, is_custom = resolve_dockerfile(dockerfile)
    rebuild(
        python_version=python_version,
        dockerfile_path=dockerfile_path,
        is_custom=is_custom,
    )
    rprint("[bold green]Done.[/bold green]")


@app.command()
def auth(
    name: str = typer.Argument(help="Name of the environment"),
    login: bool = typer.Option(
        False, "--login", help="Open interactive Claude session for /login"
    ),
) -> None:
    """
    Refresh or verify authentication credentials for an environment.
    """
    _require_docker()

    if not env_exists(name):
        rprint(f"[bold red]Error: Environment '{name}' not found.[/bold red]")
        raise typer.Exit(1)

    meta = load_meta(name)

    # Start container if needed
    if not container_is_running(meta.container_name):
        rprint(f"[dim]Starting container {meta.container_name}...[/dim]")
        container_start(meta.container_name)

    if meta.auth_mode == "subscription":
        copy_subscription_credentials(meta.container_name)
        rprint("[bold green]Subscription credentials refreshed.[/bold green]")

        if login:
            rprint("[dim]Opening interactive Claude session for /login...[/dim]")
            exec_replace(
                meta.container_name,
                ["claude"],
            )
    elif meta.auth_mode == "api_key":
        if login:
            rprint(
                "[bold red]Error: --login is not applicable for api_key mode.[/bold red]"
            )
            raise typer.Exit(1)

        try:
            env = inject_api_key(meta.api_key_env)
            key_value = env[meta.api_key_env]
            masked = key_value[:8] + "..." if len(key_value) > 8 else "***"
            rprint(f"[bold green]API key verified:[/bold green] {masked}")
        except ValueError:
            rprint(
                f"[bold red]Error: {meta.api_key_env} is not set in your environment.[/bold red]"
            )
            raise typer.Exit(1)


@app.command()
def launch(
    name: str = typer.Argument(help="Name of the environment"),
    prompt: Optional[str] = typer.Option(
        None, "--prompt", "-p", help="Prompt text to send to Claude"
    ),
    prompt_file: Optional[str] = typer.Option(
        None, "--prompt-file", help="Read prompt from a file"
    ),
    test: bool = typer.Option(
        False, "--test", help="Verify Claude can start (run claude --version)"
    ),
    background: bool = typer.Option(
        False, "--background", help="Run in background, log to file"
    ),
    inject_messaging: bool = typer.Option(
        True,
        "--inject-messaging/--no-inject-messaging",
        help="Append cage messaging instructions to the prompt",
    ),
) -> None:
    """
    Launch Claude Code inside a cage environment.
    """
    _require_docker()

    if not env_exists(name):
        rprint(f"[bold red]Error: Environment '{name}' not found.[/bold red]")
        raise typer.Exit(1)

    meta = load_meta(name)

    # Validate exactly one mode
    modes = sum([prompt is not None, prompt_file is not None, test])
    if modes == 0:
        rprint(
            "[bold red]Error: Provide --prompt, --prompt-file, or --test.[/bold red]"
        )
        raise typer.Exit(1)
    if modes > 1:
        rprint(
            "[bold red]Error: Only one of --prompt, --prompt-file, --test allowed.[/bold red]"
        )
        raise typer.Exit(1)

    # Start container if needed
    if not container_is_running(meta.container_name):
        rprint(f"[dim]Starting container {meta.container_name}...[/dim]")
        container_start(meta.container_name)

    # Build auth env
    exec_env: dict[str, str] = {}
    try:
        exec_env = get_auth_exec_env(meta)
    except ValueError:
        rprint(
            f"[bold red]Error: {meta.api_key_env} is not set. "
            "Cannot launch Claude without credentials.[/bold red]"
        )
        raise typer.Exit(1)

    # --test: quick check
    if test:
        result = container_exec(
            meta.container_name,
            ["claude", "--version"],
            user=constants.CONTAINER_USER,
            env=exec_env,
            check=False,
        )
        if result.returncode == 0:
            rprint(
                f"[bold green]Claude available:[/bold green] {result.stdout.strip()}"
            )
        else:
            rprint(
                f"[bold red]Claude not available (exit {result.returncode})[/bold red]"
            )
            raise typer.Exit(result.returncode)
        return

    # Resolve prompt text
    prompt_text = prompt
    if prompt_file:
        pf = Path(prompt_file)
        if not pf.is_file():
            rprint(f"[bold red]Error: Prompt file not found: {pf}[/bold red]")
            raise typer.Exit(1)
        prompt_text = pf.read_text()

    if inject_messaging and prompt_text:
        assets = importlib.resources.files("trusty_cage.assets")
        messaging_text = assets.joinpath("messaging-instructions.md").read_text()
        prompt_text = prompt_text + "\n\n" + messaging_text

    stream_log = f"{constants.CAGE_MSG_DIR}/claude-stream.log"
    claude_cmd = [
        "bash",
        "-c",
        f"claude -p {shlex.quote(prompt_text)} "
        f"--dangerously-skip-permissions "
        f"--output-format stream-json --verbose "
        f"2>&1 | tee {stream_log}",
    ]

    if background:
        log_path = get_env_dir(name) / "claude.log"
        docker_cmd = ["docker", "exec"]
        for k, v in exec_env.items():
            docker_cmd.extend(["-e", f"{k}={v}"])
        docker_cmd.extend(["-u", constants.CONTAINER_USER, meta.container_name])
        docker_cmd.extend(claude_cmd)

        log_file = open(log_path, "w")  # noqa: SIM115
        proc = subprocess.Popen(
            docker_cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        log_file.close()  # Popen has inherited the fd
        rprint(f"[bold green]Launched in background (PID {proc.pid})[/bold green]")
        rprint(f"[dim]Host log: {log_path}[/dim]")
        rprint(f"[dim]Stream log: tc logs {name}[/dim]")
        return

    # Foreground: stream output
    result = container_exec(
        meta.container_name,
        claude_cmd,
        user=constants.CONTAINER_USER,
        env=exec_env,
        capture=False,
    )
    raise typer.Exit(result.returncode)


def _is_inside_cage() -> bool:
    """
    Check if we're running inside a trusty-cage container.
    """
    return os.environ.get("TRUSTY_CAGE") == "1"


def _format_stream_line(line: str) -> str | None:
    """
    Parse a stream-json line and return a pretty-printed string, or None to skip.
    """
    line = line.strip()
    if not line:
        return None
    try:
        msg = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    try:
        return _format_stream_msg(msg)
    except (KeyError, TypeError, AttributeError):
        return None


def _format_stream_msg(msg: dict) -> str | None:
    """
    Format a parsed stream-json message with color-coded output.

    Color scheme:
      INIT     — bold blue (session start)
      THINKING — dim italic (collapsed to first line)
      TOOL     — yellow label, dim command/path
      RESULT   — dim (tool output, less important)
      CLAUDE   — bold white (agent's own words — most important)
      DONE     — bold green label, dim cost/duration
    """

    t = msg.get("type", "")

    if t == "system":
        model = msg.get("model", "unknown")
        sid = msg.get("session_id", "")[:8]
        return f"[bold blue]INIT[/bold blue] [dim]session={sid}... model={model}[/dim]"

    if t == "assistant":
        parts = []
        for block in msg.get("message", {}).get("content", []):
            bt = block.get("type", "")
            if bt == "thinking":
                thought = block.get("thinking", "")
                if thought:
                    first_line = thought.split("\n", 1)[0][:100]
                    parts.append(f"[dim italic]THINKING {first_line}[/dim italic]")
            elif bt == "tool_use":
                tool = block.get("name", "")
                inp = block.get("input", {})
                if tool == "Bash":
                    cmd = inp.get("command", "")[:120]
                    parts.append(f"[yellow]TOOL[/yellow] [dim]{tool}:[/dim] {cmd}")
                elif tool in ("Write", "Edit"):
                    path = inp.get("file_path", "")
                    parts.append(f"[yellow]TOOL[/yellow] [dim]{tool}:[/dim] {path}")
                elif tool == "Read":
                    path = inp.get("file_path", "")
                    parts.append(f"[yellow]TOOL[/yellow] [dim]{tool}:[/dim] {path}")
                elif tool == "Grep":
                    pattern = inp.get("pattern", "")[:80]
                    parts.append(
                        f"[yellow]TOOL[/yellow] [dim]{tool}:[/dim] /{pattern}/"
                    )
                elif tool == "Glob":
                    pattern = inp.get("pattern", "")
                    parts.append(f"[yellow]TOOL[/yellow] [dim]{tool}:[/dim] {pattern}")
                else:
                    parts.append(f"[yellow]TOOL[/yellow] [dim]{tool}[/dim]")
            elif bt == "text":
                text = block.get("text", "")
                if text:
                    parts.append(f"[bold]CLAUDE[/bold] {text[:200]}")
        return "\n".join(parts) if parts else None

    if t == "user":
        for block in msg.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                content = block.get("content", "")[:150]
                return f"[dim]RESULT {content}[/dim]"
        return None

    if t == "result":
        result_text = msg.get("result", "")[:200]
        cost = msg.get("total_cost_usd", 0)
        duration = msg.get("duration_ms", 0) / 1000
        return (
            f"[bold green]DONE[/bold green] {result_text}\n"
            f"[dim]     cost=${cost:.4f} duration={duration:.1f}s[/dim]"
        )

    return None


def _pretty_stream(input_stream: "IO[str]") -> None:
    """
    Read stream-json lines and pretty-print them.
    """
    try:
        for line in input_stream:
            formatted = _format_stream_line(line)
            if formatted:
                ts = datetime.now().strftime("%H:%M:%S")
                rprint(f"[dim]{ts}[/dim] {formatted}")
    except KeyboardInterrupt:
        pass


@app.command()
def logs(
    name: Optional[str] = typer.Argument(
        None, help="Name of the environment (not needed inside a cage)"
    ),
    follow: bool = typer.Option(
        False, "--follow", "-f", help="Follow log output (like tail -f)"
    ),
    raw: bool = typer.Option(
        False, "--raw", "-r", help="Show raw JSON instead of pretty-printed output"
    ),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
) -> None:
    """
    View the inner Claude's stream log. Works from the host or inside the cage.
    """
    stream_log = f"{constants.CAGE_MSG_DIR}/claude-stream.log"

    if _is_inside_cage():
        if follow:
            if not raw:
                proc = subprocess.Popen(
                    ["tail", "-f", "-n", str(lines), stream_log],
                    stdout=subprocess.PIPE,
                    text=True,
                )
                try:
                    _pretty_stream(proc.stdout)
                finally:
                    proc.terminate()
                    proc.wait()
            else:
                os.execlp("tail", "tail", "-f", "-n", str(lines), stream_log)
        else:
            try:
                result = subprocess.run(
                    ["tail", "-n", str(lines), stream_log],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                if not raw:
                    _pretty_stream(io.StringIO(result.stdout))
                else:
                    print(result.stdout, end="")
            except subprocess.CalledProcessError:
                rprint("[dim]No stream log found. Has Claude been launched?[/dim]")
                raise typer.Exit(1)
        return

    # Outside the container: read via docker exec
    _require_docker()

    if not name:
        rprint(
            "[bold red]Error: Environment name required when running from host.[/bold red]"
        )
        raise typer.Exit(1)

    if not env_exists(name):
        rprint(f"[bold red]Error: Environment '{name}' not found.[/bold red]")
        raise typer.Exit(1)

    meta = load_meta(name)

    if not container_is_running(meta.container_name):
        rprint("[bold red]Error: Container is not running.[/bold red]")
        raise typer.Exit(1)

    if follow:
        if not raw:
            proc = subprocess.Popen(
                [
                    "docker",
                    "exec",
                    "-u",
                    constants.CONTAINER_USER,
                    meta.container_name,
                    "tail",
                    "-f",
                    "-n",
                    str(lines),
                    stream_log,
                ],
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                _pretty_stream(proc.stdout)
            finally:
                proc.terminate()
                proc.wait()
        else:
            exec_replace(
                meta.container_name,
                ["tail", "-f", "-n", str(lines), stream_log],
            )
    else:
        result = container_exec(
            meta.container_name,
            ["tail", "-n", str(lines), stream_log],
            user=constants.CONTAINER_USER,
            check=False,
        )
        if result.returncode != 0:
            rprint("[dim]No stream log found. Has Claude been launched?[/dim]")
            raise typer.Exit(1)
        if not raw:
            _pretty_stream(io.StringIO(result.stdout))
        else:
            print(result.stdout, end="")


# ---------------------------------------------------------------------------
# Messaging commands
# ---------------------------------------------------------------------------


def _require_env_running(name: str):
    """
    Validate environment exists and container is running. Returns meta.
    """
    _require_docker()
    if not env_exists(name):
        rprint(f"[bold red]Error: Environment '{name}' not found.[/bold red]")
        raise typer.Exit(1)
    meta = load_meta(name)
    if not container_is_running(meta.container_name):
        rprint("[bold red]Error: Container is not running.[/bold red]")
        raise typer.Exit(1)
    return meta


@app.command("outbox")
def outbox_read(
    name: str = typer.Argument(help="Name of the environment"),
    all_messages: bool = typer.Option(
        False, "--all", "-a", help="Show all messages (ignore cursor)"
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON array"),
    poll: bool = typer.Option(
        False,
        "--poll",
        help="Poll until a task_complete or going_idle message arrives",
    ),
    timeout: int = typer.Option(
        1800, "--timeout", help="Poll timeout in seconds (default: 1800 = 30m)"
    ),
    interval: int = typer.Option(
        30, "--interval", help="Poll interval in seconds (default: 30)"
    ),
) -> None:
    """
    Read messages from a cage's outbox.
    """
    meta = _require_env_running(name)

    if poll:
        rprint(f"[dim]Polling outbox for task_complete (timeout: {timeout}s)...[/dim]")
        start = time.time()
        while True:
            messages = read_outbox(meta.container_name, since_cursor=True)
            for msg in messages:
                ts = msg.timestamp[11:19] if len(msg.timestamp) >= 19 else ""
                if msg.type == "progress_update":
                    rprint(
                        f"[dim]{ts}[/dim] [dim]Progress:[/dim] {msg.payload.get('status', '')}"
                    )
                elif msg.type == "error":
                    rprint(
                        f"[dim]{ts}[/dim] [bold red]Error:[/bold red] {msg.payload.get('message', '')}"
                    )
                elif msg.type == "going_idle":
                    reason = msg.payload.get("reason", "Inner agent went idle")
                    waited = msg.payload.get("waited_seconds", 0)
                    rprint(
                        f"[dim]{ts}[/dim] [bold yellow]Inner agent idle:[/bold yellow] {reason} "
                        f"(waited {waited}s)"
                    )
                    if messages:
                        set_cursor(meta.container_name, messages[-1].timestamp)
                    raise typer.Exit(2)
                elif msg.type == "task_complete":
                    summary = msg.payload.get("summary", "")
                    exit_code = msg.payload.get("exit_code", 0)
                    if exit_code == 0:
                        rprint(
                            f"[dim]{ts}[/dim] [bold green]Task complete:[/bold green] {summary}"
                        )
                    else:
                        rprint(
                            f"[dim]{ts}[/dim] [bold yellow]Task complete (exit {exit_code}):[/bold yellow] {summary}"
                        )
                    if messages:
                        set_cursor(meta.container_name, messages[-1].timestamp)
                    raise typer.Exit(exit_code)
                else:
                    rprint(f"[dim]{ts}[/dim] [dim][{msg.type}][/dim] {msg.payload}")

            if messages:
                set_cursor(meta.container_name, messages[-1].timestamp)

            elapsed = time.time() - start
            if elapsed >= timeout:
                rprint("[bold red]Timeout waiting for task_complete.[/bold red]")
                raise typer.Exit(1)

            time.sleep(interval)
        return

    messages = read_outbox(meta.container_name, since_cursor=not all_messages)

    if json_output:
        print(json.dumps([m.to_dict() for m in messages], indent=2))
        return

    if not messages:
        rprint("[dim]No messages.[/dim]")
        return

    for msg in messages:
        ts = msg.timestamp[:19] if len(msg.timestamp) >= 19 else msg.timestamp
        rprint(f"[cyan]{ts}[/cyan] [bold]{msg.type}[/bold]")
        for key, value in msg.payload.items():
            rprint(f"  {key}: {value}")

    # Advance cursor
    if not all_messages:
        set_cursor(meta.container_name, messages[-1].timestamp)


@app.command("inbox")
def inbox_send(
    name: str = typer.Argument(help="Name of the environment"),
    msg_type: str = typer.Argument(
        help="Message type (info_response, ack, task_revision)"
    ),
    payload_json: str = typer.Argument(help="Payload as JSON string"),
) -> None:
    """
    Send a message to a cage's inbox.
    """
    meta = _require_env_running(name)

    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as e:
        rprint(f"[bold red]Error: Invalid JSON payload: {e}[/bold red]")
        raise typer.Exit(1)

    msg = send_to_inbox(meta.container_name, msg_type, payload)
    rprint(f"[bold green]Sent [{msg.type}][/bold green] id={msg.id}")
