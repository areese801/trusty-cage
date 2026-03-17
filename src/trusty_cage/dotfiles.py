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

        # Strip .git/
        git_dir = clone_dir / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)

        # Copy into container home
        home = constants.CONTAINER_HOME
        copy_to_container(str(clone_dir) + "/.", container_name, home)

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
        install_scripts = ["install.sh", "install", "setup.sh", "setup"]
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
