"""
Shared paths, names, and defaults for trusty-cage.
"""

from pathlib import Path

# Host directories
TRUSTY_CAGE_DIR = Path.home() / ".trusty-cage"
ENVS_DIR = TRUSTY_CAGE_DIR / "envs"
DOTENV_PATH = TRUSTY_CAGE_DIR / ".env"
IMAGE_SHA_PATH = TRUSTY_CAGE_DIR / "image.sha"

# Docker naming
IMAGE_TAG = "trusty-cage:latest"
CONTAINER_PREFIX = "isolated-dev-"
VOLUME_PREFIX = "isolated-dev-"

# Container user
CONTAINER_USER = "trustycage"
CONTAINER_HOME = f"/home/{CONTAINER_USER}"
CONTAINER_PROJECT_DIR = f"{CONTAINER_HOME}/project"

# tmux
TMUX_SESSION = "dev"

# Environment variable names
ENV_DOTFILES_REPO = "TRUSTY_CAGE_DOTFILES_REPO"
ENV_PYTHON_VERSION = "TRUSTY_CAGE_PYTHON_VERSION"
ENV_DEFAULT_SHELL = "TRUSTY_CAGE_DEFAULT_SHELL"
ENV_DEFAULT_AUTH_MODE = "TRUSTY_CAGE_DEFAULT_AUTH_MODE"

# Defaults (used when neither env var nor .env provides a value)
DEFAULTS = {
    ENV_DOTFILES_REPO: "",
    ENV_PYTHON_VERSION: "3.12",
    ENV_DEFAULT_SHELL: "zsh",
    ENV_DEFAULT_AUTH_MODE: "api_key",
}
