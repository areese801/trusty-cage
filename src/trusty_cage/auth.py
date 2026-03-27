"""
Authentication mode handling for trusty-cage environments.

Supports two modes:
- api_key: Reads host env var at attach time, injected via docker exec -e
- subscription: Copies ~/.claude/ into container at create time, plus
  extracts OAuth tokens from macOS Keychain and writes them as
  ~/.claude/.credentials.json inside the container
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from rich import print as rprint
from rich.prompt import Prompt

from trusty_cage import constants
from trusty_cage.docker import container_exec, copy_to_container

if TYPE_CHECKING:
    from trusty_cage.environment import MetaJson


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
    Warns if ~/.claude.json is missing (needed for non-interactive claude -p).
    """
    claude_dir = Path.home() / ".claude"
    if not claude_dir.is_dir():
        return False
    claude_json = Path.home() / ".claude.json"
    if not claude_json.is_file():
        rprint(
            "[bold yellow]Warning: ~/.claude.json not found. "
            "Non-interactive 'claude -p' may fail. "
            "Run 'claude' and '/login' first.[/bold yellow]"
        )
    return True


def get_auth_exec_env(meta: MetaJson) -> dict[str, str]:
    """
    Build the env dict for docker exec based on the environment's auth mode.
    Returns empty dict for subscription mode (credentials on disk).
    Raises ValueError for api_key mode if the key is not set.
    """
    if meta.auth_mode == "api_key":
        return inject_api_key(meta.api_key_env)
    return {}


def _extract_keychain_credentials() -> str | None:
    """
    Extract Claude Code OAuth credentials from macOS Keychain.

    Returns the JSON string from the keychain, or None if not available
    (not on macOS, keychain entry missing, or access denied).
    """
    if platform.system() != "Darwin":
        return None

    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                "Claude Code-credentials",
                "-w",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        creds = result.stdout.strip()
        # Validate it's actual JSON
        json.loads(creds)
        return creds
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def copy_subscription_credentials(container_name: str) -> None:
    """
    Copy ~/.claude/ and ~/.claude.json from host into the container, then
    extract OAuth tokens from macOS Keychain and write them as
    ~/.claude/.credentials.json inside the container.

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

    # Copy ~/.claude.json (OAuth account metadata)
    claude_json = Path.home() / ".claude.json"
    if claude_json.is_file():
        dest_json = f"{constants.CONTAINER_HOME}/.claude.json"
        copy_to_container(str(claude_json), container_name, dest_json)
        container_exec(
            container_name,
            [
                "chown",
                f"{constants.CONTAINER_USER}:{constants.CONTAINER_USER}",
                dest_json,
            ],
            user="root",
        )

    # Extract OAuth tokens from macOS Keychain and write to container.
    # On macOS, Claude Code stores tokens in the system Keychain rather than
    # on disk. Linux containers have no Keychain, so Claude Code falls back to
    # reading ~/.claude/.credentials.json. We bridge the gap by extracting
    # from Keychain and writing the file-based fallback.
    keychain_creds = _extract_keychain_credentials()
    if keychain_creds:
        creds_path = f"{dest}/.credentials.json"
        container_exec(
            container_name,
            ["bash", "-c", f"cat > {creds_path}"],
            user=constants.CONTAINER_USER,
            input=keychain_creds,
        )
        container_exec(
            container_name,
            ["chmod", "600", creds_path],
            user=constants.CONTAINER_USER,
        )
        rprint("[dim]Injected OAuth tokens from macOS Keychain.[/dim]")
    else:
        rprint(
            "[bold yellow]Warning: Could not extract OAuth tokens from macOS Keychain. "
            "You may need to run 'tc auth <name> --login' to authenticate.[/bold yellow]"
        )
