"""
Shared test fixtures for trusty-cage.
"""

import pytest


@pytest.fixture
def mock_trusty_cage_dir(tmp_path, monkeypatch):
    """
    Redirect all trusty-cage paths to a temp directory.
    """
    import trusty_cage.constants as constants

    cage_dir = tmp_path / ".trusty-cage"
    cage_dir.mkdir()
    envs_dir = cage_dir / "envs"
    envs_dir.mkdir()
    dotenv_path = cage_dir / ".env"

    monkeypatch.setattr(constants, "TRUSTY_CAGE_DIR", cage_dir)
    monkeypatch.setattr(constants, "ENVS_DIR", envs_dir)
    monkeypatch.setattr(constants, "DOTENV_PATH", dotenv_path)
    monkeypatch.setattr(constants, "IMAGE_SHA_PATH", cage_dir / "image.sha")
    monkeypatch.setattr(constants, "CUSTOM_DOCKERFILE", cage_dir / "Dockerfile")

    return cage_dir
