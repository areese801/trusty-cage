"""
Configuration via CLI flags, environment variables, and .env file.

Resolution order (highest priority first):
1. CLI flags (applied by callers via resolve())
2. Environment variables set in the shell
3. Values from ~/.trusty-cage/.env
4. Built-in defaults
"""

import os

from dotenv import load_dotenv

from trusty_cage import constants


def load_config() -> dict[str, str]:
    """
    Load configuration from env vars and .env file, falling back to defaults.
    This handles layers 2-4. CLI flags (layer 1) are applied via resolve().
    """
    # Load .env file (does NOT override existing env vars)
    load_dotenv(constants.DOTENV_PATH)

    config = {}
    for env_var, default in constants.DEFAULTS.items():
        config[env_var] = os.environ.get(env_var, default)
    return config


def resolve(key: str, cli_value: str | None = None) -> str:
    """
    Resolve a single config value with full precedence:
    CLI flag > env var > .env > default.

    Pass cli_value from the Typer Option; None means the flag wasn't provided.
    """
    if cli_value is not None:
        return cli_value

    load_dotenv(constants.DOTENV_PATH)
    return os.environ.get(key, constants.DEFAULTS.get(key, ""))
