"""
Tests for CLI commands via Typer CliRunner.
"""

import subprocess

from typer.testing import CliRunner

from trusty_cage.cli import app

runner = CliRunner()

# With top-level imports in cli.py, we must mock via trusty_cage.cli namespace
# so the already-bound references in the module get patched.
CLI = "trusty_cage.cli"


class TestCreateCommand:
    def test_fails_when_docker_not_running(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=False)
        result = runner.invoke(
            app, ["create", "https://github.com/user/repo", "--no-attach"]
        )
        assert result.exit_code != 0
        assert "Docker" in result.output

    def test_fails_when_env_exists(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.env_exists", return_value=True)
        result = runner.invoke(
            app,
            [
                "create",
                "https://github.com/user/repo",
                "--name",
                "existing",
                "--no-attach",
            ],
            input="api_key\n",
        )
        assert result.exit_code != 0

    def test_create_with_auth_mode_flag_skips_prompt(
        self, mocker, mock_trusty_cage_dir, tmp_path
    ):
        """
        Passing --auth-mode should skip the interactive auth prompt.
        """
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.build_if_needed", return_value=False)
        mocker.patch(f"{CLI}.volume_create")
        mocker.patch(f"{CLI}.container_create")
        mocker.patch(f"{CLI}.container_start")
        mocker.patch(f"{CLI}.copy_to_container")
        mocker.patch(f"{CLI}.container_exec")
        mock_prompt = mocker.patch(f"{CLI}.prompt_auth_mode")

        def fake_clone(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            clone_dest = cmd[-1]
            from pathlib import Path

            dest = Path(clone_dest)
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "README.md").write_text("# Hello")
            (dest / ".git").mkdir()
            return subprocess.CompletedProcess(cmd, 0)

        mocker.patch(f"{CLI}.subprocess.run", side_effect=fake_clone)

        result = runner.invoke(
            app,
            [
                "create",
                "https://github.com/octocat/Hello-World",
                "--no-attach",
                "--auth-mode",
                "api_key",
            ],
        )
        assert result.exit_code == 0
        assert "created successfully" in result.output
        mock_prompt.assert_not_called()

    def test_create_with_invalid_auth_mode_fails(self, mocker, mock_trusty_cage_dir):
        """
        Passing an invalid --auth-mode should exit with error.
        """
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(
            app,
            [
                "create",
                "https://github.com/user/repo",
                "--no-attach",
                "--auth-mode",
                "bogus",
            ],
        )
        assert result.exit_code != 0
        assert "Invalid auth mode" in result.output

    def test_full_create_flow(self, mocker, mock_trusty_cage_dir, tmp_path):
        """
        Test the full create flow with all external calls mocked.
        """
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.build_if_needed", return_value=False)
        mocker.patch(f"{CLI}.volume_create")
        mocker.patch(f"{CLI}.container_create")
        mocker.patch(f"{CLI}.container_start")
        mocker.patch(f"{CLI}.copy_to_container")
        mocker.patch(f"{CLI}.container_exec")

        # Mock git clone to create a repo dir with a file
        def fake_clone(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            clone_dest = cmd[-1]
            from pathlib import Path

            dest = Path(clone_dest)
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "README.md").write_text("# Hello")
            (dest / ".git").mkdir()
            return subprocess.CompletedProcess(cmd, 0)

        mocker.patch(f"{CLI}.subprocess.run", side_effect=fake_clone)

        result = runner.invoke(
            app,
            ["create", "https://github.com/octocat/Hello-World", "--no-attach"],
            input="api_key\n",
        )
        assert result.exit_code == 0
        assert "created successfully" in result.output


class TestStopCommand:
    def test_fails_when_env_not_found(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(app, ["stop", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_stops_running_container(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="api_key")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mock_stop = mocker.patch(f"{CLI}.container_stop")

        result = runner.invoke(app, ["stop", "myenv"])
        assert result.exit_code == 0
        assert "Stopped" in result.output
        mock_stop.assert_called_once()

    def test_already_stopped(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="api_key")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=False)

        result = runner.invoke(app, ["stop", "myenv"])
        assert result.exit_code == 0
        assert "already stopped" in result.output


class TestListCommand:
    def test_no_environments(self, mock_trusty_cage_dir):
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "No environments" in result.output

    def test_lists_environments(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="env-a", repo_url="https://a.com/r", auth_mode="api_key")
        create_meta(name="env-b", repo_url="https://b.com/r", auth_mode="subscription")

        mocker.patch(f"{CLI}.container_is_running", return_value=True)

        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "env-a" in result.output
        assert "env-b" in result.output


class TestDestroyCommand:
    def test_fails_when_env_not_found(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(app, ["destroy", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_destroy_with_yes_flag(self, mocker, mock_trusty_cage_dir):
        """
        Passing --yes should skip the confirmation prompt.
        """
        from trusty_cage.environment import create_meta, env_exists

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="api_key")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_exists", return_value=True)
        mocker.patch(f"{CLI}.container_remove")
        mocker.patch(f"{CLI}.volume_exists", return_value=True)
        mocker.patch(f"{CLI}.volume_remove")

        result = runner.invoke(app, ["destroy", "myenv", "--yes"])
        assert result.exit_code == 0
        assert "Destroyed" in result.output
        assert not env_exists("myenv")

    def test_cancels_on_no_confirm(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="api_key")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)

        result = runner.invoke(app, ["destroy", "myenv"], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled" in result.output

    def test_destroys_environment(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta, env_exists

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="api_key")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_exists", return_value=True)
        mocker.patch(f"{CLI}.container_remove")
        mocker.patch(f"{CLI}.volume_exists", return_value=True)
        mocker.patch(f"{CLI}.volume_remove")

        result = runner.invoke(app, ["destroy", "myenv"], input="y\n")
        assert result.exit_code == 0
        assert "Destroyed" in result.output
        assert not env_exists("myenv")


class TestExportCommand:
    def test_fails_when_env_not_found(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(app, ["export", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_export_with_yes_flag(self, mocker, mock_trusty_cage_dir, tmp_path):
        """
        Passing --yes should skip the confirmation prompt.
        """
        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mocker.patch(f"{CLI}.subprocess.run")

        # Create the host clone dir so rsync target exists
        from pathlib import Path

        Path(meta.host_clone_path).mkdir(parents=True, exist_ok=True)

        result = runner.invoke(app, ["export", "myenv", "--yes"])
        assert result.exit_code == 0
        assert "Exported" in result.output

    def test_cancels_on_no_confirm(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="api_key")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)

        result = runner.invoke(app, ["export", "myenv"], input="n\n")
        assert result.exit_code == 0
        assert "Cancelled" in result.output


class TestRebuildImageCommand:
    def test_fails_when_docker_not_running(self, mocker):
        mocker.patch(f"{CLI}.is_docker_running", return_value=False)
        result = runner.invoke(app, ["rebuild-image"])
        assert result.exit_code != 0
        assert "Docker" in result.output


class TestAttachCommand:
    def test_fails_when_env_not_found(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(app, ["attach", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output
