"""
Tests for image module.
"""

import os
import subprocess

import pytest

from trusty_cage.image import (
    compute_dockerfile_sha,
    get_asset_path,
    needs_rebuild,
    resolve_dockerfile,
)


class TestGetAssetPath:
    def test_returns_dockerfile_path(self):
        path = get_asset_path("Dockerfile")
        assert path.endswith("Dockerfile")

    def test_returns_existing_file(self):
        import os

        path = get_asset_path("Dockerfile")
        assert os.path.isfile(path)


class TestComputeDockerfileSha:
    def test_returns_hex_string(self):
        sha = compute_dockerfile_sha()
        assert len(sha) == 64
        assert all(c in "0123456789abcdef" for c in sha)

    def test_is_deterministic(self):
        assert compute_dockerfile_sha() == compute_dockerfile_sha()


class TestNeedsRebuild:
    def test_needs_rebuild_when_no_image(self, mocker, mock_trusty_cage_dir):
        mocker.patch("trusty_cage.image.image_exists", return_value=False)
        assert needs_rebuild() is True

    def test_needs_rebuild_when_no_stored_sha(self, mocker, mock_trusty_cage_dir):
        mocker.patch("trusty_cage.image.image_exists", return_value=True)
        # No image.sha file exists in mock dir
        assert needs_rebuild() is True

    def test_no_rebuild_when_sha_matches(self, mocker, mock_trusty_cage_dir):
        mocker.patch("trusty_cage.image.image_exists", return_value=True)
        sha = compute_dockerfile_sha()
        (mock_trusty_cage_dir / "image.sha").write_text(sha)
        assert needs_rebuild() is False

    def test_needs_rebuild_when_sha_differs(self, mocker, mock_trusty_cage_dir):
        mocker.patch("trusty_cage.image.image_exists", return_value=True)
        (mock_trusty_cage_dir / "image.sha").write_text("stale_sha_value")
        assert needs_rebuild() is True


class TestResolveDockerfile:
    def test_cli_flag_takes_priority(self, tmp_path, mock_trusty_cage_dir):
        cli_file = tmp_path / "Custom.Dockerfile"
        cli_file.write_text("FROM ubuntu:24.04\n")

        # Also create convention file — should be ignored
        (mock_trusty_cage_dir / "Dockerfile").write_text("FROM alpine:latest\n")

        path, is_custom = resolve_dockerfile(str(cli_file))
        assert path == str(cli_file.resolve())
        assert is_custom is True

    def test_convention_path_when_no_flag(self, mock_trusty_cage_dir):
        convention = mock_trusty_cage_dir / "Dockerfile"
        convention.write_text("FROM ubuntu:24.04\n")

        path, is_custom = resolve_dockerfile(None)
        assert path == str(convention)
        assert is_custom is True

    def test_falls_back_to_bundled(self, mock_trusty_cage_dir):
        path, is_custom = resolve_dockerfile(None)
        assert path.endswith("Dockerfile")
        assert is_custom is False

    def test_cli_flag_file_not_found(self, tmp_path):
        import pytest

        with pytest.raises(FileNotFoundError):
            resolve_dockerfile(str(tmp_path / "nonexistent.Dockerfile"))

    def test_needs_rebuild_with_custom_dockerfile(
        self, mocker, mock_trusty_cage_dir, tmp_path
    ):
        custom = tmp_path / "Custom.Dockerfile"
        custom.write_text("FROM ubuntu:24.04\n")

        mocker.patch("trusty_cage.image.image_exists", return_value=True)

        # Store SHA of bundled Dockerfile — should mismatch with custom
        bundled_sha = compute_dockerfile_sha()
        (mock_trusty_cage_dir / "image.sha").write_text(bundled_sha)

        assert needs_rebuild(str(custom)) is True


class TestDockerfileContents:
    """Static checks that don't require a real Docker build."""

    def test_uv_install_is_present(self):
        dockerfile_text = open(get_asset_path("Dockerfile")).read()
        assert "astral.sh/uv/install.sh" in dockerfile_text, (
            "Dockerfile should preinstall uv so inner agents don't need to bootstrap it"
        )


@pytest.mark.docker
@pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_TESTS") != "1",
    reason="Set RUN_DOCKER_TESTS=1 to run real docker build tests",
)
class TestImageBuildIntegration:
    """Real-build tests. Slow; skipped unless RUN_DOCKER_TESTS=1 is set."""

    def test_uv_preinstalled(self):
        from trusty_cage import constants
        from trusty_cage.image import rebuild

        rebuild()
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "/usr/bin/zsh",
                constants.IMAGE_TAG,
                "-lc",
                "uv --version",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"uv --version failed in built image: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert result.stdout.startswith("uv "), (
            f"Expected uv version banner, got: {result.stdout!r}"
        )
