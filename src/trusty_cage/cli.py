"""
CLI entry point for trusty-cage.
"""

from typing import Optional

import typer
from rich import print as rprint

app = typer.Typer(
    name="trusty-cage",
    help="Isolated Docker-based development environments for AI coding agents.",
    no_args_is_help=True,
)


@app.command()
def create(
    git_repo_url: str = typer.Argument(help="URL of the git repository to clone"),
    name: Optional[str] = typer.Option(None, help="Override the derived environment name"),
    no_attach: bool = typer.Option(False, "--no-attach", help="Create without attaching"),
) -> None:
    """
    Create a new isolated development environment from a git repo.
    """
    rprint("[yellow]create command not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command()
def attach(
    name: str = typer.Argument(help="Name of the environment to attach to"),
) -> None:
    """
    Attach to an existing environment's interactive tmux session.
    """
    rprint("[yellow]attach command not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command()
def stop(
    name: str = typer.Argument(help="Name of the environment to stop"),
) -> None:
    """
    Stop an environment's container (preserves volume).
    """
    rprint("[yellow]stop command not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command("list")
def list_envs() -> None:
    """
    List all environments with status, creation date, and repo URL.
    """
    rprint("[yellow]list command not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command()
def export(
    name: str = typer.Argument(help="Name of the environment to export"),
) -> None:
    """
    Export work from container back to host clone.
    """
    rprint("[yellow]export command not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command()
def destroy(
    name: str = typer.Argument(help="Name of the environment to destroy"),
) -> None:
    """
    Destroy an environment's container and volume (keeps host clone).
    """
    rprint("[yellow]destroy command not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command("rebuild-image")
def rebuild_image() -> None:
    """
    Force rebuild the Docker image from scratch.
    """
    from trusty_cage.config import resolve
    from trusty_cage.constants import ENV_PYTHON_VERSION
    from trusty_cage.docker import is_docker_running
    from trusty_cage.image import rebuild

    if not is_docker_running():
        rprint("[bold red]Error: Docker is not running.[/bold red]")
        raise typer.Exit(1)

    python_version = resolve(ENV_PYTHON_VERSION)
    rebuild(python_version=python_version)
    rprint("[bold green]Done.[/bold green]")
