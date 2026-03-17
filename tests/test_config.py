"""
Tests for config module.
"""

from trusty_cage.config import load_config, resolve
from trusty_cage.constants import (
    ENV_DEFAULT_AUTH_MODE,
    ENV_DEFAULT_SHELL,
    ENV_DOTFILES_REPO,
    ENV_PYTHON_VERSION,
)


class TestLoadConfig:
    def test_returns_defaults_when_nothing_set(self, mock_trusty_cage_dir, monkeypatch):
        """
        load_config returns defaults when no env vars or .env file exist.
        """
        # Clear any env vars that might be set
        for key in [ENV_DOTFILES_REPO, ENV_PYTHON_VERSION, ENV_DEFAULT_SHELL, ENV_DEFAULT_AUTH_MODE]:
            monkeypatch.delenv(key, raising=False)

        config = load_config()
        assert config[ENV_PYTHON_VERSION] == "3.12"
        assert config[ENV_DEFAULT_SHELL] == "zsh"
        assert config[ENV_DEFAULT_AUTH_MODE] == "api_key"
        assert config[ENV_DOTFILES_REPO] == ""

    def test_env_var_overrides_default(self, mock_trusty_cage_dir, monkeypatch):
        """
        An env var takes precedence over the built-in default.
        """
        monkeypatch.setenv(ENV_PYTHON_VERSION, "3.13")
        config = load_config()
        assert config[ENV_PYTHON_VERSION] == "3.13"

    def test_dotenv_file_provides_values(self, mock_trusty_cage_dir, monkeypatch):
        """
        Values in .env file are used when env vars aren't set.
        """
        for key in [ENV_DOTFILES_REPO, ENV_PYTHON_VERSION, ENV_DEFAULT_SHELL, ENV_DEFAULT_AUTH_MODE]:
            monkeypatch.delenv(key, raising=False)

        dotenv_path = mock_trusty_cage_dir / ".env"
        dotenv_path.write_text(f'{ENV_DOTFILES_REPO}=https://github.com/user/dots\n')

        config = load_config()
        assert config[ENV_DOTFILES_REPO] == "https://github.com/user/dots"

    def test_env_var_overrides_dotenv(self, mock_trusty_cage_dir, monkeypatch):
        """
        A real env var beats a .env file value.
        """
        dotenv_path = mock_trusty_cage_dir / ".env"
        dotenv_path.write_text(f'{ENV_PYTHON_VERSION}=3.11\n')
        monkeypatch.setenv(ENV_PYTHON_VERSION, "3.13")

        config = load_config()
        assert config[ENV_PYTHON_VERSION] == "3.13"


class TestResolve:
    def test_cli_value_wins_over_everything(self, mock_trusty_cage_dir, monkeypatch):
        """
        CLI flag value takes highest priority.
        """
        monkeypatch.setenv(ENV_PYTHON_VERSION, "3.13")
        result = resolve(ENV_PYTHON_VERSION, cli_value="3.14")
        assert result == "3.14"

    def test_falls_back_to_env_var(self, mock_trusty_cage_dir, monkeypatch):
        """
        Without CLI flag, env var is used.
        """
        monkeypatch.setenv(ENV_PYTHON_VERSION, "3.13")
        result = resolve(ENV_PYTHON_VERSION)
        assert result == "3.13"

    def test_falls_back_to_default(self, mock_trusty_cage_dir, monkeypatch):
        """
        Without CLI flag or env var, default is used.
        """
        monkeypatch.delenv(ENV_PYTHON_VERSION, raising=False)
        result = resolve(ENV_PYTHON_VERSION)
        assert result == "3.12"

    def test_none_cli_value_is_not_used(self, mock_trusty_cage_dir, monkeypatch):
        """
        None means flag wasn't passed — doesn't count as a value.
        """
        monkeypatch.setenv(ENV_PYTHON_VERSION, "3.13")
        result = resolve(ENV_PYTHON_VERSION, cli_value=None)
        assert result == "3.13"
