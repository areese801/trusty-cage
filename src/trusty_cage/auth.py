"""
Authentication mode handling for trusty-cage environments.

Supports two modes:
- api_key: Reads host env var at attach time, injected via docker exec -e
- subscription: Copies ~/.claude/ into container at create time
"""

import os
import shutil
import tempfile
from pathlib import Path

from rich import print as rprint
from rich.prompt import Prompt

from trusty_cage import constants
from trusty_cage.docker import container_exec, copy_to_container


def prompt_auth_mode(default: str = "api_key") -> str:
    """
    Interactively prompt the user to choose an authentication mode.
    Returns 'api_key' or 'subscription'.
    """
    modes = ["api_key", "subscription"]
    descriptions = {
        "api_key": "Inject ANTHROPIC_API_KEY at attach time",
        "subscription": "Copy ~/.claude/ credentials into container",
    }
    default_num = str(modes.index(default) + 1)

    rprint("\n[bold]Authentication mode:[/bold]")
    for i, mode in enumerate(modes, 1):
        marker = " (default)" if mode == default else ""
        rprint(f"  [cyan]{i}[/cyan]) {mode} — {descriptions[mode]}{marker}")
    rprint()

    choice = Prompt.ask(
        "Choose auth mode",
        choices=["1", "2", "api_key", "subscription"],
        default=default_num,
    )

    if choice in ("1", "2"):
        return modes[int(choice) - 1]
    return choice


def get_api_key_env_value(env_var: str = "ANTHROPIC_API_KEY") -> str | None:
    """
    Read the API key from the host environment.
    Returns None if the variable is not set or empty.
    """
    value = os.environ.get(env_var, "").strip()
    return value if value else None


def inject_api_key(
    api_key_env: str = "ANTHROPIC_API_KEY",
) -> dict[str, str]:
    """
    Build an env dict for docker exec -e to inject the API key.
    Raises ValueError if the key is not set on the host.
    """
    value = get_api_key_env_value(api_key_env)
    if value is None:
        raise ValueError(
            f"Environment variable {api_key_env} is not set. "
            "Export it in your shell before attaching."
        )
    return {api_key_env: value}


def validate_subscription_credentials() -> bool:
    """
    Check if ~/.claude/ exists on the host with credential files.
    """
    claude_dir = Path.home() / ".claude"
    return claude_dir.is_dir()


def copy_subscription_credentials(container_name: str) -> None:
    """
    Copy ~/.claude/ from host into the container, then chown.
    Raises FileNotFoundError if ~/.claude/ doesn't exist.
    """
    claude_dir = Path.home() / ".claude"
    if not claude_dir.is_dir():
        raise FileNotFoundError(
            f"~/.claude/ not found at {claude_dir}. Cannot use subscription auth mode."
        )

    dest = f"{constants.CONTAINER_HOME}/.claude"

    # Copy to a temp dir with symlinks dereferenced so docker cp doesn't choke
    # on symlinks (e.g. GNU Stow-managed dotfiles).
    with tempfile.TemporaryDirectory() as tmp:
        resolved = Path(tmp) / ".claude"
        shutil.copytree(claude_dir, resolved, symlinks=False)
        copy_to_container(str(resolved) + "/.", container_name, dest)

    container_exec(
        container_name,
        ["chown", "-R", f"{constants.CONTAINER_USER}:{constants.CONTAINER_USER}", dest],
        user="root",
    )
