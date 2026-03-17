"""
Authentication mode handling for trusty-cage environments.

Supports two modes:
- api_key: Reads host env var at attach time, injected via docker exec -e
- subscription: Copies ~/.claude/ into container at create time
"""

import os
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
    rprint("\n[bold]Authentication mode:[/bold]")
    rprint(
        "  [cyan]api_key[/cyan]      — Inject ANTHROPIC_API_KEY at attach time (default)"
    )
    rprint("  [cyan]subscription[/cyan] — Copy ~/.claude/ credentials into container\n")

    choice = Prompt.ask(
        "Choose auth mode",
        choices=["api_key", "subscription"],
        default=default,
    )
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
    copy_to_container(str(claude_dir) + "/.", container_name, dest)
    container_exec(
        container_name,
        ["chown", "-R", f"{constants.CONTAINER_USER}:{constants.CONTAINER_USER}", dest],
        user="root",
    )
