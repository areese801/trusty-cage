"""
CLI entry point for trusty-cage.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.prompt import Confirm
from rich.table import Table

from trusty_cage import constants
from trusty_cage.auth import (
    copy_subscription_credentials,
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
    create_meta,
    derive_name,
    env_exists,
    get_env_dir,
    list_envs as get_all_envs,
    load_meta,
)
from trusty_cage.image import build_if_needed, rebuild
from trusty_cage.network import apply_network_policy

app = typer.Typer(
    name="trusty-cage",
    help="Isolated Docker-based development environments for AI coding agents.",
    no_args_is_help=True,
)


def _require_docker() -> None:
    """
    Exit with error if Docker is not running.
    """
    if not is_docker_running():
        rprint("[bold red]Error: Docker is not running.[/bold red]")
        raise typer.Exit(1)


@app.command()
def create(
    git_repo_url: str = typer.Argument(help="URL of the git repository to clone"),
    name: Optional[str] = typer.Option(
        None, help="Override the derived environment name"
    ),
    no_attach: bool = typer.Option(
        False, "--no-attach", help="Create without attaching"
    ),
) -> None:
    """
    Create a new isolated development environment from a git repo.
    """
    _require_docker()

    # Derive or validate name
    env_name = name if name else derive_name(git_repo_url)
    if env_exists(env_name):
        rprint(f"[bold red]Error: Environment '{env_name}' already exists.[/bold red]")
        raise typer.Exit(1)

    # Prompt for auth mode
    default_auth = resolve(constants.ENV_DEFAULT_AUTH_MODE)
    auth_mode = prompt_auth_mode(default=default_auth)

    if auth_mode == "subscription" and not validate_subscription_credentials():
        rprint(
            "[bold red]Error: ~/.claude/ not found. Cannot use subscription mode.[/bold red]"
        )
        raise typer.Exit(1)

    # Build image if needed
    python_version = resolve(constants.ENV_PYTHON_VERSION)
    build_if_needed(python_version=python_version)

    # Git clone to host
    env_dir = get_env_dir(env_name)
    host_clone = env_dir / "repo"
    host_clone.mkdir(parents=True, exist_ok=True)

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

    # Write meta.json
    meta = create_meta(
        name=env_name,
        repo_url=git_repo_url,
        auth_mode=auth_mode,
    )

    # Create volume and container
    volume_create(meta.volume_name)
    rprint(f"[dim]Created volume {meta.volume_name}[/dim]")

    volume_mount = f"{meta.volume_name}:{constants.CONTAINER_PROJECT_DIR}"
    container_create(
        name=meta.container_name,
        image=constants.IMAGE_TAG,
        volume_mount=volume_mount,
        hostname=env_name,
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

    # Init local git inside container (no remotes)
    container_exec(
        meta.container_name,
        ["git", "init"],
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
    if meta.auth_mode == "api_key":
        try:
            exec_env = inject_api_key(meta.api_key_env)
        except ValueError as e:
            rprint(f"[bold red]Error: {e}[/bold red]")
            raise typer.Exit(1)

    # Check if tmux session exists
    tmux_check = container_exec(
        meta.container_name,
        ["tmux", "has-session", "-t", constants.TMUX_SESSION],
        user=constants.CONTAINER_USER,
        env=exec_env,
        check=False,
    )

    if tmux_check.returncode != 0:
        # Create 3-window layout: editor, claude, shell
        container_exec(
            meta.container_name,
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                constants.TMUX_SESSION,
                "-n",
                "editor",
            ],
            user=constants.CONTAINER_USER,
            env=exec_env,
        )
        container_exec(
            meta.container_name,
            ["tmux", "new-window", "-t", f"{constants.TMUX_SESSION}", "-n", "claude"],
            user=constants.CONTAINER_USER,
            env=exec_env,
        )
        container_exec(
            meta.container_name,
            ["tmux", "new-window", "-t", f"{constants.TMUX_SESSION}", "-n", "shell"],
            user=constants.CONTAINER_USER,
            env=exec_env,
        )
        # Select first window
        container_exec(
            meta.container_name,
            ["tmux", "select-window", "-t", f"{constants.TMUX_SESSION}:0"],
            user=constants.CONTAINER_USER,
            env=exec_env,
        )
        rprint(
            "[dim]Created tmux session with 3 windows (editor, claude, shell).[/dim]"
        )

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
def list_envs() -> None:
    """
    List all environments with status, creation date, and repo URL.
    """
    envs = get_all_envs()
    if not envs:
        rprint("[dim]No environments found.[/dim]")
        return

    table = Table(title="trusty-cage environments")
    table.add_column("Name", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Repo", style="dim")
    table.add_column("Created", style="dim")
    table.add_column("Auth", style="dim")

    for meta in envs:
        try:
            running = container_is_running(meta.container_name)
            status = "[green]running[/green]" if running else "[yellow]stopped[/yellow]"
        except Exception:
            status = "[red]unknown[/red]"

        created = (
            meta.created_at[:10] if len(meta.created_at) >= 10 else meta.created_at
        )
        table.add_row(meta.name, status, meta.repo_url, created, meta.auth_mode)

    rprint(table)


@app.command()
def export(
    name: str = typer.Argument(help="Name of the environment to export"),
) -> None:
    """
    Export work from container back to host clone.
    """
    _require_docker()

    if not env_exists(name):
        rprint(f"[bold red]Error: Environment '{name}' not found.[/bold red]")
        raise typer.Exit(1)

    meta = load_meta(name)

    if not Confirm.ask(f"Export container files to {meta.host_clone_path}?"):
        rprint("[dim]Cancelled.[/dim]")
        return

    # Ensure container is running for docker cp
    was_stopped = False
    if not container_is_running(meta.container_name):
        container_start(meta.container_name)
        was_stopped = True

    # Copy project dir from container to temp dir
    with tempfile.TemporaryDirectory(prefix="trusty-cage-export-") as tmpdir:
        export_dir = Path(tmpdir) / "project"
        copy_from_container(
            meta.container_name,
            constants.CONTAINER_PROJECT_DIR + "/.",
            str(export_dir),
        )

        # Remove .git/ from exported files (container has its own local git)
        exported_git = export_dir / ".git"
        if exported_git.exists():
            shutil.rmtree(exported_git)

        # rsync into host clone, preserving host's .git/
        host_clone = Path(meta.host_clone_path)
        subprocess.run(
            [
                "rsync",
                "-a",
                "--delete",
                "--exclude",
                ".git/",
                str(export_dir) + "/",
                str(host_clone) + "/",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    if was_stopped:
        container_stop(meta.container_name)

    rprint(f"[bold green]Exported to {meta.host_clone_path}[/bold green]")
    rprint("[dim]Suggested workflow:[/dim]")
    rprint(f"  cd {meta.host_clone_path}")
    rprint("  git diff")
    rprint("  git add -A && git commit -m 'work from trusty-cage'")
    rprint("  git push")


@app.command()
def destroy(
    name: str = typer.Argument(help="Name of the environment to destroy"),
) -> None:
    """
    Destroy an environment's container and volume (keeps host clone).
    """
    _require_docker()

    if not env_exists(name):
        rprint(f"[bold red]Error: Environment '{name}' not found.[/bold red]")
        raise typer.Exit(1)

    meta = load_meta(name)

    if not Confirm.ask(
        f"Destroy environment '{name}'? Container and volume will be removed."
    ):
        rprint("[dim]Cancelled.[/dim]")
        return

    # Remove container
    if container_exists(meta.container_name):
        container_remove(meta.container_name, force=True)
        rprint(f"[dim]Removed container {meta.container_name}[/dim]")

    # Remove volume
    if volume_exists(meta.volume_name):
        volume_remove(meta.volume_name)
        rprint(f"[dim]Removed volume {meta.volume_name}[/dim]")

    # Delete meta.json (keep repo/)
    meta_path = get_env_dir(name) / "meta.json"
    if meta_path.exists():
        meta_path.unlink()

    rprint(f"[bold green]Destroyed '{name}'.[/bold green]")
    rprint(f"[dim]Host clone preserved at {meta.host_clone_path}[/dim]")


@app.command("rebuild-image")
def rebuild_image() -> None:
    """
    Force rebuild the Docker image from scratch.
    """
    _require_docker()

    python_version = resolve(constants.ENV_PYTHON_VERSION)
    rebuild(python_version=python_version)
    rprint("[bold green]Done.[/bold green]")
