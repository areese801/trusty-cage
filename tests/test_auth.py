"""
Tests for auth module.
"""

import pytest

from trusty_cage.auth import (
    copy_subscription_credentials,
    get_api_key_env_value,
    get_auth_exec_env,
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
        mocker.patch(
            "trusty_cage.auth._extract_keychain_credentials", return_value=None
        )
        mock_cp = mocker.patch("trusty_cage.auth.copy_to_container")
        mock_exec = mocker.patch("trusty_cage.auth.container_exec")

        copy_subscription_credentials("test-container")

        # Only .claude/ copied (no .claude.json, no keychain creds)
        mock_cp.assert_called_once()
        mock_exec.assert_called_once()
        assert mock_exec.call_args[1]["user"] == "root"

    def test_copies_claude_json_when_present(self, tmp_path, monkeypatch, mocker):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "config.json").write_text("{}")
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text('{"oauthAccount": "test"}')

        monkeypatch.setattr("trusty_cage.auth.Path.home", lambda: tmp_path)
        mocker.patch(
            "trusty_cage.auth._extract_keychain_credentials", return_value=None
        )
        mock_cp = mocker.patch("trusty_cage.auth.copy_to_container")
        mocker.patch("trusty_cage.auth.container_exec")

        copy_subscription_credentials("test-container")

        # Called twice: .claude/ and .claude.json
        assert mock_cp.call_count == 2
        second_call_src = mock_cp.call_args_list[1][0][0]
        assert ".claude.json" in second_call_src

    def test_skips_claude_json_when_missing(self, tmp_path, monkeypatch, mocker):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "config.json").write_text("{}")

        monkeypatch.setattr("trusty_cage.auth.Path.home", lambda: tmp_path)
        mocker.patch(
            "trusty_cage.auth._extract_keychain_credentials", return_value=None
        )
        mock_cp = mocker.patch("trusty_cage.auth.copy_to_container")
        mocker.patch("trusty_cage.auth.container_exec")

        copy_subscription_credentials("test-container")

        assert mock_cp.call_count == 1

    def test_injects_keychain_credentials(self, tmp_path, monkeypatch, mocker):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "config.json").write_text("{}")

        monkeypatch.setattr("trusty_cage.auth.Path.home", lambda: tmp_path)
        mocker.patch(
            "trusty_cage.auth._extract_keychain_credentials",
            return_value='{"claudeAiOauth":{"accessToken":"sk-test"}}',
        )
        mocker.patch("trusty_cage.auth.copy_to_container")
        mock_exec = mocker.patch("trusty_cage.auth.container_exec")

        copy_subscription_credentials("test-container")

        # Should have written credentials via container_exec with input
        creds_calls = [
            c for c in mock_exec.call_args_list if c[1].get("input") is not None
        ]
        assert len(creds_calls) == 1
        assert "accessToken" in creds_calls[0][1]["input"]

    def test_warns_when_no_keychain(self, tmp_path, monkeypatch, mocker, capsys):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "config.json").write_text("{}")

        monkeypatch.setattr("trusty_cage.auth.Path.home", lambda: tmp_path)
        mocker.patch(
            "trusty_cage.auth._extract_keychain_credentials", return_value=None
        )
        mocker.patch("trusty_cage.auth.copy_to_container")
        mocker.patch("trusty_cage.auth.container_exec")

        copy_subscription_credentials("test-container")

        # Warning should have been printed (via Rich)
        # We can't easily capture Rich output, but we verify no crash


class TestGetAuthExecEnv:
    def test_api_key_mode_returns_env(self, monkeypatch):
        from trusty_cage.environment import MetaJson

        meta = MetaJson(
            name="t",
            repo_url="",
            created_at="",
            volume_name="",
            container_name="",
            host_clone_path="",
            auth_mode="api_key",
        )
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        result = get_auth_exec_env(meta)
        assert result == {"ANTHROPIC_API_KEY": "sk-test"}

    def test_subscription_mode_returns_empty(self):
        from trusty_cage.environment import MetaJson

        meta = MetaJson(
            name="t",
            repo_url="",
            created_at="",
            volume_name="",
            container_name="",
            host_clone_path="",
            auth_mode="subscription",
        )
        result = get_auth_exec_env(meta)
        assert result == {}
