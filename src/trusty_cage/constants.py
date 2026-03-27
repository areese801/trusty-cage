"""
Shared paths, names, and defaults for trusty-cage.
"""

from pathlib import Path

# Host directories
TRUSTY_CAGE_DIR = Path.home() / ".trusty-cage"
ENVS_DIR = TRUSTY_CAGE_DIR / "envs"
DOTENV_PATH = TRUSTY_CAGE_DIR / ".env"
IMAGE_SHA_PATH = TRUSTY_CAGE_DIR / "image.sha"
CUSTOM_DOCKERFILE = TRUSTY_CAGE_DIR / "Dockerfile"

# Docker naming
IMAGE_TAG = "trusty-cage:latest"
CONTAINER_PREFIX = "isolated-dev-"
VOLUME_PREFIX = "isolated-dev-"

# Container user
CONTAINER_USER = "trustycage"
CONTAINER_HOME = f"/home/{CONTAINER_USER}"
CONTAINER_PROJECT_DIR = f"{CONTAINER_HOME}/project"

# Messaging directories (inside container)
CAGE_MSG_DIR = f"{CONTAINER_HOME}/.cage"
CAGE_OUTBOX_DIR = f"{CAGE_MSG_DIR}/outbox"
CAGE_INBOX_DIR = f"{CAGE_MSG_DIR}/inbox"
CAGE_CURSOR_DIR = f"{CAGE_MSG_DIR}/cursor"
CAGE_OUTBOX_CURSOR = f"{CAGE_CURSOR_DIR}/outbox.cursor"
CAGE_INBOX_CURSOR = f"{CAGE_CURSOR_DIR}/inbox.cursor"

# tmux
TMUX_SESSION = "dev"

# Environment variable names
ENV_DOTFILES_REPO = "TRUSTY_CAGE_DOTFILES_REPO"
ENV_PYTHON_VERSION = "TRUSTY_CAGE_PYTHON_VERSION"
ENV_DEFAULT_SHELL = "TRUSTY_CAGE_DEFAULT_SHELL"
ENV_DEFAULT_AUTH_MODE = "TRUSTY_CAGE_DEFAULT_AUTH_MODE"
ENV_TMUX_PREFIX = "TRUSTY_CAGE_TMUX_PREFIX"

# Valid auth modes
AUTH_MODES = ("api_key", "subscription")

# Defaults (used when neither env var nor .env provides a value)
DEFAULTS = {
    ENV_DOTFILES_REPO: "",
    ENV_PYTHON_VERSION: "3.12",
    ENV_DEFAULT_SHELL: "zsh",
    ENV_DEFAULT_AUTH_MODE: "api_key",
    ENV_TMUX_PREFIX: "C-a",
}
