"""
Tests for auth module.
"""

import pytest

from trusty_cage.auth import (
    copy_subscription_credentials,
    get_api_key_env_value,
    inject_api_key,
    validate_subscription_credentials,
)


class TestGetApiKeyEnvValue:
    def test_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
        assert get_api_key_env_value() == "sk-ant-test-key"

    def test_returns_none_when_not_set(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert get_api_key_env_value() is None

    def test_returns_none_when_empty(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        assert get_api_key_env_value() is None

    def test_returns_none_when_whitespace(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
        assert get_api_key_env_value() is None

    def test_custom_env_var(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "custom-value")
        assert get_api_key_env_value("MY_KEY") == "custom-value"


class TestInjectApiKey:
    def test_returns_env_dict(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        result = inject_api_key()
        assert result == {"ANTHROPIC_API_KEY": "sk-test"}

    def test_raises_when_key_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError, match="not set"):
            inject_api_key()

    def test_custom_env_var(self, monkeypatch):
        monkeypatch.setenv("CUSTOM_KEY", "val")
        result = inject_api_key("CUSTOM_KEY")
        assert result == {"CUSTOM_KEY": "val"}


class TestValidateSubscriptionCredentials:
    def test_true_when_claude_dir_exists(self, tmp_path, monkeypatch):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        monkeypatch.setattr("trusty_cage.auth.Path.home", lambda: tmp_path)
        assert validate_subscription_credentials() is True

    def test_false_when_claude_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trusty_cage.auth.Path.home", lambda: tmp_path)
        assert validate_subscription_credentials() is False


class TestCopySubscriptionCredentials:
    def test_raises_when_no_claude_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("trusty_cage.auth.Path.home", lambda: tmp_path)
        with pytest.raises(FileNotFoundError, match=".claude"):
            copy_subscription_credentials("test-container")

    def test_copies_and_chowns(self, tmp_path, monkeypatch, mocker):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "config.json").write_text("{}")

        monkeypatch.setattr("trusty_cage.auth.Path.home", lambda: tmp_path)
        mock_cp = mocker.patch("trusty_cage.auth.copy_to_container")
        mock_exec = mocker.patch("trusty_cage.auth.container_exec")

        copy_subscription_credentials("test-container")

        mock_cp.assert_called_once()
        mock_exec.assert_called_once()
        # Verify chown was called as root
        assert mock_exec.call_args[1]["user"] == "root"
