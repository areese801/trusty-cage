"""
Tests for the init CLI command.
"""

from typer.testing import CliRunner

from trusty_cage.cli import app

runner = CliRunner()


class TestInitCommand:
    def test_creates_env_file(self, mock_trusty_cage_dir):
        env_path = mock_trusty_cage_dir / ".env"
        assert not env_path.exists()

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        assert env_path.exists()
        assert "Created" in result.output

        contents = env_path.read_text()
        assert "TRUSTY_CAGE_DOTFILES_REPO" in contents
        assert "TRUSTY_CAGE_PYTHON_VERSION" in contents

    def test_skips_if_env_exists(self, mock_trusty_cage_dir):
        env_path = mock_trusty_cage_dir / ".env"
        env_path.write_text("existing content")

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        assert "already exists" in result.output
        assert env_path.read_text() == "existing content"

    def test_force_overwrites_existing(self, mock_trusty_cage_dir):
        env_path = mock_trusty_cage_dir / ".env"
        env_path.write_text("existing content")

        result = runner.invoke(app, ["init", "--force"])

        assert result.exit_code == 0
        assert "Created" in result.output
        assert "TRUSTY_CAGE_DOTFILES_REPO" in env_path.read_text()

    def test_creates_config_dir_if_missing(self, tmp_path, monkeypatch):
        import trusty_cage.constants as constants

        cage_dir = tmp_path / "fresh" / ".trusty-cage"
        monkeypatch.setattr(constants, "TRUSTY_CAGE_DIR", cage_dir)
        monkeypatch.setattr(constants, "DOTENV_PATH", cage_dir / ".env")

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        assert cage_dir.exists()
        assert (cage_dir / ".env").exists()
