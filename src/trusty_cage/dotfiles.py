"""
Dotfiles management for trusty-cage environments.

Clones a dotfiles repo on the host, strips .git/, copies into the container,
runs an install script if present, and chowns everything.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from rich import print as rprint

from trusty_cage import constants
from trusty_cage.docker import container_exec, copy_to_container


def apply_dotfiles(container_name: str, dotfiles_repo: str) -> None:
    """
    Apply dotfiles from a git repo into a container.

    1. Clone repo to a temp directory on the host
    2. Strip .git/ directory
    3. docker cp contents into container home
    4. Run install script if found (install.sh, install, setup.sh, setup)
    5. chown everything to container user
    """
    if not dotfiles_repo:
        return

    with tempfile.TemporaryDirectory(prefix="trusty-cage-dots-") as tmpdir:
        clone_dir = Path(tmpdir) / "dotfiles"

        rprint(f"[dim]Cloning dotfiles from {dotfiles_repo}...[/dim]")
        subprocess.run(
            ["git", "clone", "--depth", "1", dotfiles_repo, str(clone_dir)],
            check=True,
            capture_output=True,
            text=True,
        )

        # Strip .git/ and git submodule dirs
        git_dir = clone_dir / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)

        # Detect GNU Stow layout: if a "common/" subdirectory exists with
        # dotfiles (hidden files/dirs), copy from there instead of the root.
        # This handles repos structured as ~/.dotfiles/common/.tmux.conf etc.
        stow_dir = clone_dir / "common"
        if stow_dir.is_dir() and any(
            p.name.startswith(".") for p in stow_dir.iterdir()
        ):
            source_dir = stow_dir
            rprint("[dim]Detected GNU Stow layout, copying from common/[/dim]")
        else:
            source_dir = clone_dir

        # Remove broken symlinks (docker cp rejects them)
        for p in source_dir.rglob("*"):
            if p.is_symlink() and not p.resolve().exists():
                rprint(f"[dim]Removing broken symlink: {p.relative_to(source_dir)}[/dim]")
                p.unlink()

        # Copy into container home
        home = constants.CONTAINER_HOME
        copy_to_container(str(source_dir) + "/.", container_name, home)

        # chown
        container_exec(
            container_name,
            [
                "chown",
                "-R",
                f"{constants.CONTAINER_USER}:{constants.CONTAINER_USER}",
                home,
            ],
            user="root",
        )

        # Run install script if present
        install_scripts = ["install.sh", "install", "setup.sh", "setup", "bootstrap.sh"]
        for script_name in install_scripts:
            result = container_exec(
                container_name,
                ["test", "-f", f"{home}/{script_name}"],
                user=constants.CONTAINER_USER,
                capture=True,
                check=False,
            )
            if result.returncode == 0:
                rprint(f"[dim]Running dotfiles installer: {script_name}[/dim]")
                container_exec(
                    container_name,
                    ["chmod", "+x", f"{home}/{script_name}"],
                    user=constants.CONTAINER_USER,
                )
                container_exec(
                    container_name,
                    ["bash", f"{home}/{script_name}"],
                    user=constants.CONTAINER_USER,
                    capture=False,
                )
                break

    rprint("[dim]Dotfiles applied.[/dim]")
