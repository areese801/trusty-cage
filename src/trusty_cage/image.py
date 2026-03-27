"""
Dockerfile SHA tracking and image build management.
"""

import hashlib
import importlib.resources
from pathlib import Path

from rich import print as rprint

from trusty_cage import constants
from trusty_cage.docker import build_image, image_exists


def get_asset_path(filename: str) -> str:
    """
    Get the filesystem path to a bundled asset file.
    """
    assets = importlib.resources.files("trusty_cage.assets")
    resource = assets.joinpath(filename)
    # For editable installs, this is already a real path
    return str(resource)


def resolve_dockerfile(cli_path: str | None = None) -> tuple[str, bool]:
    """
    Resolve which Dockerfile to use.

    Priority:
      1. --dockerfile CLI flag (highest)
      2. ~/.trusty-cage/Dockerfile (convention path)
      3. Bundled Dockerfile (fallback)

    Returns (dockerfile_path, is_custom).
    """
    if cli_path:
        path = Path(cli_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Custom Dockerfile not found: {path}")
        return str(path), True

    if constants.CUSTOM_DOCKERFILE.is_file():
        return str(constants.CUSTOM_DOCKERFILE), True

    return get_asset_path("Dockerfile"), False


def _warn_custom_dockerfile(dockerfile_path: str) -> None:
    """
    Print a warning when using a custom Dockerfile.
    """
    rprint(
        f"\n[bold yellow]WARNING: Using custom Dockerfile: {dockerfile_path}[/bold yellow]\n"
        "[yellow]This replaces the default trusty-cage image entirely. You are responsible for\n"
        "ensuring the image includes the trustycage user (UID 1000), required tools, and\n"
        "any security constraints your workflow requires.\n"
        "If running Claude Code inside this container, consider whether\n"
        "--dangerously-skip-permissions is appropriate for your image.[/yellow]\n"
    )


def compute_dockerfile_sha(dockerfile_path: str | None = None) -> str:
    """
    Compute SHA-256 of the given Dockerfile (or the bundled one by default).
    """
    if dockerfile_path is None:
        dockerfile_path = get_asset_path("Dockerfile")
    with open(dockerfile_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _read_stored_sha() -> str | None:
    """
    Read the stored Dockerfile SHA from disk.
    """
    if constants.IMAGE_SHA_PATH.exists():
        return constants.IMAGE_SHA_PATH.read_text().strip()
    return None


def _write_stored_sha(sha: str) -> None:
    """
    Write the Dockerfile SHA to disk.
    """
    constants.TRUSTY_CAGE_DIR.mkdir(parents=True, exist_ok=True)
    constants.IMAGE_SHA_PATH.write_text(sha)


def needs_rebuild(dockerfile_path: str | None = None) -> bool:
    """
    Check if the Docker image needs to be rebuilt.
    Returns True if image doesn't exist or Dockerfile has changed.
    """
    if not image_exists(constants.IMAGE_TAG):
        return True
    stored_sha = _read_stored_sha()
    if stored_sha is None:
        return True
    return compute_dockerfile_sha(dockerfile_path) != stored_sha


def build_if_needed(
    python_version: str = "3.12",
    dockerfile_path: str | None = None,
    is_custom: bool = False,
) -> bool:
    """
    Build the Docker image if needed.
    Returns True if a build was performed.
    """
    if not needs_rebuild(dockerfile_path):
        rprint("[dim]Docker image is up to date.[/dim]")
        return False
    return rebuild(
        python_version=python_version,
        dockerfile_path=dockerfile_path,
        is_custom=is_custom,
    )


def rebuild(
    python_version: str = "3.12",
    dockerfile_path: str | None = None,
    is_custom: bool = False,
) -> bool:
    """
    Force rebuild the Docker image.
    """
    if dockerfile_path is None:
        dockerfile_path = get_asset_path("Dockerfile")
        context_dir = get_asset_path("")  # assets directory
    else:
        context_dir = str(Path(dockerfile_path).parent)

    if is_custom:
        _warn_custom_dockerfile(dockerfile_path)

    rprint(f"[bold blue]Building Docker image {constants.IMAGE_TAG}...[/bold blue]")
    build_image(
        tag=constants.IMAGE_TAG,
        dockerfile_path=dockerfile_path,
        context_dir=context_dir,
        build_args={"PYTHON_VERSION": python_version},
    )
    _write_stored_sha(compute_dockerfile_sha(dockerfile_path))
    rprint(f"[bold green]Image {constants.IMAGE_TAG} built successfully.[/bold green]")
    return True
