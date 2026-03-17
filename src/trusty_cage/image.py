"""
Dockerfile SHA tracking and image build management.
"""

import hashlib
import importlib.resources

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


def compute_dockerfile_sha() -> str:
    """
    Compute SHA-256 of the bundled Dockerfile.
    """
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


def needs_rebuild() -> bool:
    """
    Check if the Docker image needs to be rebuilt.
    Returns True if image doesn't exist or Dockerfile has changed.
    """
    if not image_exists(constants.IMAGE_TAG):
        return True
    stored_sha = _read_stored_sha()
    if stored_sha is None:
        return True
    return compute_dockerfile_sha() != stored_sha


def build_if_needed(python_version: str = "3.12") -> bool:
    """
    Build the Docker image if needed.
    Returns True if a build was performed.
    """
    if not needs_rebuild():
        rprint("[dim]Docker image is up to date.[/dim]")
        return False
    return rebuild(python_version=python_version)


def rebuild(python_version: str = "3.12") -> bool:
    """
    Force rebuild the Docker image.
    """
    dockerfile_path = get_asset_path("Dockerfile")
    context_dir = get_asset_path("")  # assets directory

    rprint(f"[bold blue]Building Docker image {constants.IMAGE_TAG}...[/bold blue]")
    build_image(
        tag=constants.IMAGE_TAG,
        dockerfile_path=dockerfile_path,
        context_dir=context_dir,
        build_args={"PYTHON_VERSION": python_version},
    )
    _write_stored_sha(compute_dockerfile_sha())
    rprint(f"[bold green]Image {constants.IMAGE_TAG} built successfully.[/bold green]")
    return True
