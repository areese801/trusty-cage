"""
Tests for image module.
"""

from trusty_cage.image import (
    compute_dockerfile_sha,
    get_asset_path,
    needs_rebuild,
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
