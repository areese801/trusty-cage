"""
Tests for environment module.
"""

import json

from trusty_cage.environment import (
    MetaJson,
    create_meta,
    derive_name,
    env_exists,
    get_env_dir,
    list_envs,
    load_meta,
)


class TestDeriveName:
    def test_https_url(self):
        assert derive_name("https://github.com/octocat/Hello-World") == "hello-world"

    def test_url_with_git_suffix(self):
        assert (
            derive_name("https://github.com/octocat/Hello-World.git") == "hello-world"
        )

    def test_ssh_url(self):
        assert derive_name("git@github.com:octocat/Hello-World.git") == "hello-world"

    def test_trailing_slash(self):
        assert derive_name("https://github.com/octocat/Hello-World/") == "hello-world"

    def test_sanitizes_special_chars(self):
        assert derive_name("https://example.com/user/my repo!") == "my-repo-"


class TestGetEnvDir:
    def test_returns_path_under_envs(self, mock_trusty_cage_dir):
        env_dir = get_env_dir("myenv")
        assert env_dir.name == "myenv"
        assert env_dir.parent.name == "envs"


class TestEnvExists:
    def test_false_when_no_meta(self, mock_trusty_cage_dir):
        assert env_exists("nonexistent") is False

    def test_true_when_meta_exists(self, mock_trusty_cage_dir):
        env_dir = get_env_dir("myenv")
        env_dir.mkdir(parents=True)
        (env_dir / "meta.json").write_text("{}")
        assert env_exists("myenv") is True


class TestCreateMeta:
    def test_creates_meta_file(self, mock_trusty_cage_dir):
        meta = create_meta(
            name="test-env",
            repo_url="https://github.com/user/repo",
            auth_mode="api_key",
        )
        assert meta.name == "test-env"
        assert meta.repo_url == "https://github.com/user/repo"
        assert meta.auth_mode == "api_key"
        assert meta.volume_name == "isolated-dev-test-env"
        assert meta.container_name == "isolated-dev-test-env"

        meta_path = get_env_dir("test-env") / "meta.json"
        assert meta_path.is_file()
        data = json.loads(meta_path.read_text())
        assert data["name"] == "test-env"

    def test_sets_created_at(self, mock_trusty_cage_dir):
        meta = create_meta(
            name="test-env",
            repo_url="https://github.com/user/repo",
            auth_mode="api_key",
        )
        assert "T" in meta.created_at  # ISO format


class TestLoadMeta:
    def test_loads_existing_meta(self, mock_trusty_cage_dir):
        create_meta(
            name="test-env",
            repo_url="https://github.com/user/repo",
            auth_mode="subscription",
        )
        loaded = load_meta("test-env")
        assert loaded.name == "test-env"
        assert loaded.auth_mode == "subscription"

    def test_raises_when_missing(self, mock_trusty_cage_dir):
        import pytest

        with pytest.raises(FileNotFoundError):
            load_meta("nonexistent")


class TestListEnvs:
    def test_empty_when_no_envs(self, mock_trusty_cage_dir):
        assert list_envs() == []

    def test_lists_multiple_envs(self, mock_trusty_cage_dir):
        create_meta(name="env-a", repo_url="https://a.com/repo", auth_mode="api_key")
        create_meta(
            name="env-b", repo_url="https://b.com/repo", auth_mode="subscription"
        )
        envs = list_envs()
        assert len(envs) == 2
        names = [e.name for e in envs]
        assert "env-a" in names
        assert "env-b" in names

    def test_skips_invalid_meta(self, mock_trusty_cage_dir):
        create_meta(name="good", repo_url="https://a.com/repo", auth_mode="api_key")
        bad_dir = get_env_dir("bad")
        bad_dir.mkdir(parents=True)
        (bad_dir / "meta.json").write_text("not json")
        envs = list_envs()
        assert len(envs) == 1
        assert envs[0].name == "good"


class TestMetaJson:
    def test_roundtrip(self):
        meta = MetaJson(
            name="test",
            repo_url="https://example.com/repo",
            created_at="2024-01-01T00:00:00+00:00",
            volume_name="isolated-dev-test",
            container_name="isolated-dev-test",
            host_clone_path="/tmp/test/repo",
            auth_mode="api_key",
        )
        data = meta.to_dict()
        restored = MetaJson.from_dict(data)
        assert restored.name == "test"
        assert restored.auth_mode == "api_key"
        assert restored.api_key_env == "ANTHROPIC_API_KEY"

    def test_from_dict_ignores_extra_keys(self):
        data = {
            "name": "test",
            "repo_url": "url",
            "created_at": "now",
            "volume_name": "vol",
            "container_name": "con",
            "host_clone_path": "/tmp",
            "auth_mode": "api_key",
            "extra_key": "ignored",
        }
        meta = MetaJson.from_dict(data)
        assert meta.name == "test"
