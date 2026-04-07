"""
Tests for CLI commands via Typer CliRunner.
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from trusty_cage import __version__
from trusty_cage.cli import app
from trusty_cage.environment import (
    AdditionalDir,
    MetaJson,
    create_meta,
    get_env_dir,
    load_meta,
    save_meta,
)
from trusty_cage.messaging import Message

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
        mocker.patch(f"{CLI}.container_exists", return_value=False)
        mocker.patch(f"{CLI}.volume_exists", return_value=False)
        mocker.patch(f"{CLI}.volume_create")
        mocker.patch(f"{CLI}.container_create")
        mocker.patch(f"{CLI}.container_start")
        mocker.patch(f"{CLI}.copy_to_container")
        mocker.patch(f"{CLI}.container_exec")
        mocker.patch(f"{CLI}.init_messaging_dirs")
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
        mocker.patch(f"{CLI}.container_exists", return_value=False)
        mocker.patch(f"{CLI}.volume_exists", return_value=False)
        mocker.patch(f"{CLI}.volume_create")
        mocker.patch(f"{CLI}.container_create")
        mocker.patch(f"{CLI}.container_start")
        mocker.patch(f"{CLI}.copy_to_container")
        mocker.patch(f"{CLI}.container_exec")
        mocker.patch(f"{CLI}.init_messaging_dirs")

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


class TestCreateFromDir:
    """Tests for tc create --dir."""

    def _mock_create_deps(self, mocker, mock_trusty_cage_dir):
        """Mock all external dependencies for create --dir tests."""
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.build_if_needed")
        mocker.patch(f"{CLI}.container_exists", return_value=False)
        mocker.patch(f"{CLI}.volume_exists", return_value=False)
        mocker.patch(f"{CLI}.volume_create")
        mocker.patch(f"{CLI}.container_create")
        mocker.patch(f"{CLI}.container_start")
        mocker.patch(f"{CLI}.copy_to_container")
        mocker.patch(f"{CLI}.container_exec")
        mocker.patch(f"{CLI}.init_messaging_dirs")

        def fake_rsync(*args, **kwargs):
            """Simulate rsync by creating dest dir with a marker file."""
            cmd = args[0] if args else kwargs.get("args", [])
            # rsync dest is the last arg (ends with /)
            dest = cmd[-1].rstrip("/")
            from pathlib import Path

            Path(dest).mkdir(parents=True, exist_ok=True)
            (Path(dest) / "README.md").write_text("# copied")
            return subprocess.CompletedProcess(cmd, 0)

        mocker.patch(f"{CLI}.subprocess.run", side_effect=fake_rsync)

    def test_create_with_dir_flag(self, mocker, mock_trusty_cage_dir, tmp_path):
        self._mock_create_deps(mocker, mock_trusty_cage_dir)
        source = tmp_path / "myproject"
        source.mkdir()
        (source / "main.py").write_text("print('hello')")

        result = runner.invoke(
            app,
            ["create", "--dir", str(source), "--no-attach", "--auth-mode", "api_key"],
        )
        assert result.exit_code == 0
        assert "created successfully" in result.output

    def test_create_dir_derives_name(self, mocker, mock_trusty_cage_dir, tmp_path):
        self._mock_create_deps(mocker, mock_trusty_cage_dir)
        source = tmp_path / "My-Cool-Project"
        source.mkdir()
        (source / "README.md").write_text("# hello")

        result = runner.invoke(
            app,
            ["create", "--dir", str(source), "--no-attach", "--auth-mode", "api_key"],
        )
        assert result.exit_code == 0
        assert "my-cool-project" in result.output

    def test_create_dir_with_explicit_name(
        self, mocker, mock_trusty_cage_dir, tmp_path
    ):
        self._mock_create_deps(mocker, mock_trusty_cage_dir)
        source = tmp_path / "myproject"
        source.mkdir()
        (source / "main.py").write_text("print('hello')")

        result = runner.invoke(
            app,
            [
                "create",
                "--dir",
                str(source),
                "--name",
                "custom-name",
                "--no-attach",
                "--auth-mode",
                "api_key",
            ],
        )
        assert result.exit_code == 0
        assert "custom-name" in result.output

    def test_create_dir_and_url_both_errors(
        self, mocker, mock_trusty_cage_dir, tmp_path
    ):
        source = tmp_path / "myproject"
        source.mkdir()

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(
            app,
            [
                "create",
                "https://github.com/user/repo",
                "--dir",
                str(source),
                "--no-attach",
            ],
        )
        assert result.exit_code != 0
        assert "not both" in result.output

    def test_create_neither_dir_nor_url_errors(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(app, ["create", "--no-attach"])
        assert result.exit_code != 0
        assert "Provide a git repo URL or --dir" in result.output

    def test_create_dir_nonexistent_errors(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(
            app, ["create", "--dir", "/tmp/does-not-exist-xyz", "--no-attach"]
        )
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_create_dir_meta_has_empty_repo_url(
        self, mocker, mock_trusty_cage_dir, tmp_path
    ):
        self._mock_create_deps(mocker, mock_trusty_cage_dir)
        source = tmp_path / "myproject"
        source.mkdir()
        (source / "main.py").write_text("print('hello')")

        result = runner.invoke(
            app,
            ["create", "--dir", str(source), "--no-attach", "--auth-mode", "api_key"],
        )
        assert result.exit_code == 0

        from trusty_cage.environment import load_meta

        meta = load_meta("myproject")
        assert meta.repo_url == ""


class TestSeedGitignore:
    """Tests for _seed_gitignore helper."""

    def test_seeds_python_gitignore(self, tmp_path):
        from trusty_cage.cli import _seed_gitignore

        (tmp_path / "main.py").write_text("print('hi')")
        result = _seed_gitignore(tmp_path)
        assert result is True
        content = (tmp_path / ".gitignore").read_text()
        assert "__pycache__/" in content
        assert "venv/" in content
        assert ".DS_Store" in content

    def test_seeds_node_gitignore(self, tmp_path):
        from trusty_cage.cli import _seed_gitignore

        (tmp_path / "index.js").write_text("console.log('hi')")
        result = _seed_gitignore(tmp_path)
        assert result is True
        content = (tmp_path / ".gitignore").read_text()
        assert "node_modules/" in content
        assert ".DS_Store" in content

    def test_seeds_both_python_and_node(self, tmp_path):
        from trusty_cage.cli import _seed_gitignore

        (tmp_path / "app.py").write_text("")
        (tmp_path / "package.json").write_text("{}")
        result = _seed_gitignore(tmp_path)
        assert result is True
        content = (tmp_path / ".gitignore").read_text()
        assert "__pycache__/" in content
        assert "node_modules/" in content

    def test_skips_if_gitignore_exists(self, tmp_path):
        from trusty_cage.cli import _seed_gitignore

        (tmp_path / ".gitignore").write_text("custom/\n")
        (tmp_path / "main.py").write_text("")
        result = _seed_gitignore(tmp_path)
        assert result is False
        assert (tmp_path / ".gitignore").read_text() == "custom/\n"

    def test_seeds_universal_only_for_unknown_language(self, tmp_path):
        from trusty_cage.cli import _seed_gitignore

        (tmp_path / "data.csv").write_text("a,b,c")
        result = _seed_gitignore(tmp_path)
        assert result is True
        content = (tmp_path / ".gitignore").read_text()
        assert ".DS_Store" in content
        assert "__pycache__/" not in content
        assert "node_modules/" not in content


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


class TestVersionFlag:
    def test_version_output(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert f"trusty-cage {__version__}" in result.output


class TestListJsonFlag:
    def test_list_json_empty(self, mock_trusty_cage_dir):
        result = runner.invoke(app, ["list", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []

    def test_list_json_with_envs(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="env-a", repo_url="https://a.com/r", auth_mode="api_key")
        create_meta(name="env-b", repo_url="https://b.com/r", auth_mode="subscription")

        mocker.patch(f"{CLI}.container_exists", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)

        result = runner.invoke(app, ["list", "--json"])
        assert result.exit_code == 0
        entries = json.loads(result.output)
        assert len(entries) == 2
        names = {e["name"] for e in entries}
        assert names == {"env-a", "env-b"}
        for entry in entries:
            assert set(entry.keys()) == {
                "name",
                "status",
                "repo_url",
                "created_at",
                "auth_mode",
                "additional_dirs",
            }
            assert entry["status"] == "running"


class TestExistsCommand:
    def test_exists_returns_0_when_env_exists(self, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="api_key")

        result = runner.invoke(app, ["exists", "myenv"])
        assert result.exit_code == 0
        assert result.output == ""

    def test_exists_returns_1_when_env_missing(self, mock_trusty_cage_dir):
        result = runner.invoke(app, ["exists", "nonexistent"])
        assert result.exit_code == 1
        assert result.output == ""


class TestExportOutputDir:
    def test_export_with_output_dir(self, mocker, mock_trusty_cage_dir, tmp_path):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="api_key")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(f"{CLI}.subprocess.run")

        output_dir = tmp_path / "custom-export"
        output_dir.mkdir()

        result = runner.invoke(
            app, ["export", "myenv", "--yes", "--output-dir", str(output_dir)]
        )
        assert result.exit_code == 0
        assert "Exported" in result.output

        # Verify rsync was called with the custom output dir
        rsync_call = mock_rsync.call_args
        rsync_cmd = rsync_call[0][0]
        assert str(output_dir) + "/" == rsync_cmd[-1]

    def test_export_with_nonexistent_output_dir(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="api_key")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)

        result = runner.invoke(
            app,
            ["export", "myenv", "--yes", "--output-dir", "/tmp/does-not-exist-xyz"],
        )
        assert result.exit_code == 1
        assert "does not exist" in result.output


class TestExportGitignoreExcludes:
    def test_no_gitignore_only_excludes_git(
        self, mocker, mock_trusty_cage_dir, tmp_path
    ):
        """
        Without a .gitignore, rsync should only exclude .git/.
        """
        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(f"{CLI}.subprocess.run")

        from pathlib import Path

        Path(meta.host_clone_path).mkdir(parents=True, exist_ok=True)

        result = runner.invoke(app, ["export", "myenv", "--yes"])
        assert result.exit_code == 0

        rsync_cmd = mock_rsync.call_args[0][0]
        # Only one --exclude pair: .git/
        exclude_args = [
            rsync_cmd[i + 1]
            for i in range(len(rsync_cmd))
            if rsync_cmd[i] == "--exclude"
        ]
        assert exclude_args == [
            ".git/",
            ".cageprotect",
            "venv/",
            ".venv/",
            "__pycache__/",
            "*.py[cod]",
            ".pytest_cache/",
            ".ruff_cache/",
            ".mypy_cache/",
            ".DS_Store",
            "node_modules/",
        ]

    def test_gitignore_patterns_added_as_excludes(
        self, mocker, mock_trusty_cage_dir, tmp_path
    ):
        """
        .gitignore entries should appear as additional --exclude flags.
        """
        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(f"{CLI}.subprocess.run")

        from pathlib import Path

        host_clone = Path(meta.host_clone_path)
        host_clone.mkdir(parents=True, exist_ok=True)
        (host_clone / ".gitignore").write_text("venv/\n.env\n__pycache__/\n")

        result = runner.invoke(app, ["export", "myenv", "--yes"])
        assert result.exit_code == 0

        rsync_cmd = mock_rsync.call_args[0][0]
        exclude_args = [
            rsync_cmd[i + 1]
            for i in range(len(rsync_cmd))
            if rsync_cmd[i] == "--exclude"
        ]
        # venv/ and __pycache__/ from .gitignore are deduped (already in defaults)
        assert exclude_args == [
            ".git/",
            ".cageprotect",
            "venv/",
            ".venv/",
            "__pycache__/",
            "*.py[cod]",
            ".pytest_cache/",
            ".ruff_cache/",
            ".mypy_cache/",
            ".DS_Store",
            "node_modules/",
            ".env",
        ]

    def test_gitignore_skips_comments_and_blanks(
        self, mocker, mock_trusty_cage_dir, tmp_path
    ):
        """
        Comments and blank lines in .gitignore should be ignored.
        """
        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(f"{CLI}.subprocess.run")

        from pathlib import Path

        host_clone = Path(meta.host_clone_path)
        host_clone.mkdir(parents=True, exist_ok=True)
        (host_clone / ".gitignore").write_text(
            "# Python artifacts\n\nvenv/\n\n# Secrets\n.env\n  \n"
        )

        result = runner.invoke(app, ["export", "myenv", "--yes"])
        assert result.exit_code == 0

        rsync_cmd = mock_rsync.call_args[0][0]
        exclude_args = [
            rsync_cmd[i + 1]
            for i in range(len(rsync_cmd))
            if rsync_cmd[i] == "--exclude"
        ]
        # venv/ from .gitignore is deduped; cache defaults appear before .env
        assert exclude_args == [
            ".git/",
            ".cageprotect",
            "venv/",
            ".venv/",
            "__pycache__/",
            "*.py[cod]",
            ".pytest_cache/",
            ".ruff_cache/",
            ".mypy_cache/",
            ".DS_Store",
            "node_modules/",
            ".env",
        ]


class TestAttachCommand:
    def test_fails_when_env_not_found(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(app, ["attach", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestAuthCommand:
    def test_fails_when_env_not_found(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(app, ["auth", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_subscription_recopies_credentials(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="subscription")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mock_copy = mocker.patch(f"{CLI}.copy_subscription_credentials")

        result = runner.invoke(app, ["auth", "myenv"])
        assert result.exit_code == 0
        assert "refreshed" in result.output
        mock_copy.assert_called_once()

    def test_api_key_validates_env_var(self, mocker, monkeypatch, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="api_key")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test123456")

        result = runner.invoke(app, ["auth", "myenv"])
        assert result.exit_code == 0
        assert "sk-ant-t" in result.output

    def test_api_key_login_flag_errors(self, mocker, monkeypatch, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="api_key")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)

        result = runner.invoke(app, ["auth", "myenv", "--login"])
        assert result.exit_code != 0
        assert "not applicable" in result.output


class TestLaunchCommand:
    def test_fails_when_env_not_found(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(app, ["launch", "nonexistent", "--test"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_requires_prompt_or_test(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="subscription")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)

        result = runner.invoke(app, ["launch", "myenv"])
        assert result.exit_code != 0
        assert "--prompt" in result.output

    def test_launch_test_runs_claude_version(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="subscription")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mock_exec = mocker.patch(
            f"{CLI}.container_exec",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="claude 1.0.0", stderr=""
            ),
        )

        result = runner.invoke(app, ["launch", "myenv", "--test"])
        assert result.exit_code == 0
        assert "Claude available" in result.output
        # Verify claude --version was called
        cmd = mock_exec.call_args[0][1]
        assert cmd == ["claude", "--version"]

    def test_launch_with_prompt(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="subscription")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mock_exec = mocker.patch(
            f"{CLI}.container_exec",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        )

        result = runner.invoke(app, ["launch", "myenv", "--prompt", "say hello"])
        assert result.exit_code == 0
        cmd = mock_exec.call_args[0][1]
        # Command is ["bash", "-c", "claude -p 'say hello' ..."]
        assert cmd[0] == "bash"
        assert "say hello" in cmd[2]

    def test_launch_api_key_injects_env(
        self, mocker, monkeypatch, mock_trusty_cage_dir
    ):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="api_key")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        mock_exec = mocker.patch(
            f"{CLI}.container_exec",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        )

        result = runner.invoke(app, ["launch", "myenv", "--prompt", "hello"])
        assert result.exit_code == 0
        call_kwargs = mock_exec.call_args[1]
        assert "ANTHROPIC_API_KEY" in call_kwargs.get("env", {})

    def test_launch_prompt_file(self, mocker, mock_trusty_cage_dir, tmp_path):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="subscription")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mock_exec = mocker.patch(
            f"{CLI}.container_exec",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        )

        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("Build me a thing")

        result = runner.invoke(
            app, ["launch", "myenv", "--prompt-file", str(prompt_file)]
        )
        assert result.exit_code == 0
        cmd = mock_exec.call_args[0][1]
        assert "Build me a thing" in cmd[2]


class TestOutboxPollGoingIdle:
    """Test that --poll exits with code 2 on going_idle message."""

    def test_poll_exits_on_going_idle(self):
        """tc outbox --poll should exit with code 2 when going_idle is received."""
        mock_meta = MagicMock()
        mock_meta.container_name = "isolated-dev-test"

        going_idle_msg = Message(
            id="msg-test-idle",
            type="going_idle",
            timestamp="2026-03-28T15:00:00.000Z",
            payload={"reason": "No task_revision received", "waited_seconds": 3600},
            version=1,
        )

        with (
            patch("trusty_cage.cli._require_env_running", return_value=mock_meta),
            patch("trusty_cage.cli.read_outbox", return_value=[going_idle_msg]),
            patch("trusty_cage.cli.set_cursor"),
        ):
            runner = CliRunner()
            result = runner.invoke(app, ["outbox", "test", "--poll"])
            assert result.exit_code == 2
            assert "Inner agent idle" in result.output
            assert "3600" in result.output

    def test_poll_continues_past_progress_then_exits_on_going_idle(self):
        """Non-terminal messages don't stop polling; going_idle does."""
        mock_meta = MagicMock()
        mock_meta.container_name = "isolated-dev-test"

        progress_msg = Message(
            id="msg-test-progress",
            type="progress_update",
            timestamp="2026-03-28T14:00:00.000Z",
            payload={"status": "working", "detail": "halfway done"},
            version=1,
        )
        going_idle_msg = Message(
            id="msg-test-idle",
            type="going_idle",
            timestamp="2026-03-28T15:00:00.000Z",
            payload={"reason": "No task_revision received", "waited_seconds": 3600},
            version=1,
        )

        with (
            patch("trusty_cage.cli._require_env_running", return_value=mock_meta),
            patch(
                "trusty_cage.cli.read_outbox",
                return_value=[progress_msg, going_idle_msg],
            ),
            patch("trusty_cage.cli.set_cursor"),
        ):
            runner = CliRunner()
            result = runner.invoke(app, ["outbox", "test", "--poll"])
            assert result.exit_code == 2


class TestExportDeleteDefault:
    """Export should NOT use --delete by default; opt-in with --delete flag."""

    def test_export_default_no_delete(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        Path(meta.host_clone_path).mkdir(parents=True, exist_ok=True)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(f"{CLI}.subprocess.run")

        result = runner.invoke(app, ["export", "myenv", "--yes"])
        assert result.exit_code == 0

        rsync_cmd = mock_rsync.call_args[0][0]
        assert "--delete" not in rsync_cmd

    def test_export_with_delete_flag(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        Path(meta.host_clone_path).mkdir(parents=True, exist_ok=True)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(f"{CLI}.subprocess.run")

        result = runner.invoke(app, ["export", "myenv", "--yes", "--delete"])
        assert result.exit_code == 0

        rsync_cmd = mock_rsync.call_args[0][0]
        assert "--delete" in rsync_cmd


class TestExportProtect:
    """Export --protect and .cageprotect patterns become rsync --exclude flags."""

    def test_protect_flag_adds_excludes(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        Path(meta.host_clone_path).mkdir(parents=True, exist_ok=True)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(f"{CLI}.subprocess.run")

        result = runner.invoke(
            app,
            ["export", "myenv", "--yes", "--protect", "*.md", "--protect", "*.env"],
        )
        assert result.exit_code == 0

        rsync_cmd = mock_rsync.call_args[0][0]
        assert "--exclude" in rsync_cmd
        excludes = [
            rsync_cmd[i + 1]
            for i in range(len(rsync_cmd))
            if rsync_cmd[i] == "--exclude"
        ]
        assert "*.md" in excludes
        assert "*.env" in excludes

    def test_cageprotect_file_patterns(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        host_clone = Path(meta.host_clone_path)
        host_clone.mkdir(parents=True, exist_ok=True)
        (host_clone / ".cageprotect").write_text("secrets/\n# comment\n\nbackup.sql\n")

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(f"{CLI}.subprocess.run")

        result = runner.invoke(app, ["export", "myenv", "--yes"])
        assert result.exit_code == 0

        rsync_cmd = mock_rsync.call_args[0][0]
        excludes = [
            rsync_cmd[i + 1]
            for i in range(len(rsync_cmd))
            if rsync_cmd[i] == "--exclude"
        ]
        assert "secrets/" in excludes
        assert "backup.sql" in excludes
        assert "# comment" not in excludes

    def test_gitignore_and_cageprotect_merged(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        host_clone = Path(meta.host_clone_path)
        host_clone.mkdir(parents=True, exist_ok=True)
        (host_clone / ".gitignore").write_text("venv/\n__pycache__/\n")
        (host_clone / ".cageprotect").write_text("secrets/\nvenv/\n")

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(f"{CLI}.subprocess.run")

        result = runner.invoke(app, ["export", "myenv", "--yes"])
        assert result.exit_code == 0

        rsync_cmd = mock_rsync.call_args[0][0]
        excludes = [
            rsync_cmd[i + 1]
            for i in range(len(rsync_cmd))
            if rsync_cmd[i] == "--exclude"
        ]
        assert excludes.count("venv/") == 1
        assert "__pycache__/" in excludes
        assert "secrets/" in excludes


class TestCacheExcludes:
    """Cache/build artifacts are excluded by default from export, diff, sync."""

    def test_export_excludes_cache_by_default(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        Path(meta.host_clone_path).mkdir(parents=True, exist_ok=True)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(f"{CLI}.subprocess.run")

        result = runner.invoke(app, ["export", "myenv", "--yes"])
        assert result.exit_code == 0

        rsync_cmd = mock_rsync.call_args[0][0]
        excludes = [
            rsync_cmd[i + 1]
            for i in range(len(rsync_cmd))
            if rsync_cmd[i] == "--exclude"
        ]
        assert "__pycache__/" in excludes
        assert "*.py[cod]" in excludes
        assert ".pytest_cache/" in excludes
        assert ".ruff_cache/" in excludes
        assert ".mypy_cache/" in excludes
        assert ".DS_Store" in excludes
        assert "node_modules/" in excludes

    def test_export_include_cache_skips_defaults(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        Path(meta.host_clone_path).mkdir(parents=True, exist_ok=True)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(f"{CLI}.subprocess.run")

        result = runner.invoke(app, ["export", "myenv", "--yes", "--include-cache"])
        assert result.exit_code == 0

        rsync_cmd = mock_rsync.call_args[0][0]
        excludes = [
            rsync_cmd[i + 1]
            for i in range(len(rsync_cmd))
            if rsync_cmd[i] == "--exclude"
        ]
        assert "__pycache__/" not in excludes
        assert ".pytest_cache/" not in excludes

    def test_diff_excludes_cache_by_default(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        Path(meta.host_clone_path).mkdir(parents=True, exist_ok=True)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(
            f"{CLI}.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        )

        result = runner.invoke(app, ["diff", "myenv"])
        assert result.exit_code == 0

        rsync_cmd = mock_rsync.call_args[0][0]
        excludes = [
            rsync_cmd[i + 1]
            for i in range(len(rsync_cmd))
            if rsync_cmd[i] == "--exclude"
        ]
        assert "__pycache__/" in excludes
        assert ".pytest_cache/" in excludes


class TestDiffCommand:
    """Tests for tc diff."""

    def test_fails_when_env_not_found(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(app, ["diff", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_diff_no_changes(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        Path(meta.host_clone_path).mkdir(parents=True, exist_ok=True)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mocker.patch(
            f"{CLI}.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        )

        result = runner.invoke(app, ["diff", "myenv"])
        assert result.exit_code == 0
        assert "No differences" in result.output

    def test_diff_summary_output(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        Path(meta.host_clone_path).mkdir(parents=True, exist_ok=True)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")

        rsync_output = (
            ">f+++++++++ new_file.py\n>f.st...... changed.py\n*deleting   old_file.py\n"
        )
        mocker.patch(
            f"{CLI}.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=rsync_output, stderr=""
            ),
        )

        result = runner.invoke(app, ["diff", "myenv"])
        assert result.exit_code == 0
        assert "new_file.py" in result.output
        assert "changed.py" in result.output
        assert "old_file.py" in result.output
        assert "3 file(s) changed" in result.output

    def test_diff_respects_excludes(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        host_clone = Path(meta.host_clone_path)
        host_clone.mkdir(parents=True, exist_ok=True)
        (host_clone / ".gitignore").write_text("venv/\n")

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(
            f"{CLI}.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        )

        result = runner.invoke(app, ["diff", "myenv"])
        assert result.exit_code == 0

        rsync_cmd = mock_rsync.call_args[0][0]
        excludes = [
            rsync_cmd[i + 1]
            for i in range(len(rsync_cmd))
            if rsync_cmd[i] == "--exclude"
        ]
        assert ".git/" in excludes
        assert "venv/" in excludes
        assert "--dry-run" in rsync_cmd
        assert "-i" in rsync_cmd

    def test_diff_default_excludes_delete_flag(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        Path(meta.host_clone_path).mkdir(parents=True, exist_ok=True)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(
            f"{CLI}.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        )

        result = runner.invoke(app, ["diff", "myenv"])
        assert result.exit_code == 0
        rsync_cmd = mock_rsync.call_args[0][0]
        assert "--delete" not in rsync_cmd

    def test_diff_with_delete_flag_includes_deletions(
        self, mocker, mock_trusty_cage_dir
    ):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        Path(meta.host_clone_path).mkdir(parents=True, exist_ok=True)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(
            f"{CLI}.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        )

        result = runner.invoke(app, ["diff", "myenv", "--delete"])
        assert result.exit_code == 0
        rsync_cmd = mock_rsync.call_args[0][0]
        assert "--delete" in rsync_cmd

    def test_diff_with_output_dir(self, mocker, mock_trusty_cage_dir, tmp_path):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="api_key")

        output_dir = tmp_path / "custom"
        output_dir.mkdir()

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mock_rsync = mocker.patch(
            f"{CLI}.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        )

        result = runner.invoke(app, ["diff", "myenv", "--output-dir", str(output_dir)])
        assert result.exit_code == 0

        rsync_cmd = mock_rsync.call_args[0][0]
        assert str(output_dir) + "/" == rsync_cmd[-1]


class TestSyncCommand:
    """Tests for tc sync."""

    def test_fails_when_env_not_found(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(app, ["sync", "nonexistent", "--yes"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_sync_all_files(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        host_clone = Path(meta.host_clone_path)
        host_clone.mkdir(parents=True, exist_ok=True)
        (host_clone / "main.py").write_text("print('hello')")

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mock_rsync = mocker.patch(f"{CLI}.subprocess.run")
        mocker.patch(f"{CLI}.copy_to_container")
        mocker.patch(f"{CLI}.container_exec")

        result = runner.invoke(app, ["sync", "myenv", "--yes"])
        assert result.exit_code == 0
        assert "Synced" in result.output
        assert "all files" in result.output

        rsync_cmd = mock_rsync.call_args[0][0]
        assert rsync_cmd[0] == "rsync"
        assert str(host_clone) + "/" in rsync_cmd

    def test_sync_specific_files(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        host_clone = Path(meta.host_clone_path)
        host_clone.mkdir(parents=True, exist_ok=True)
        (host_clone / "main.py").write_text("print('hello')")

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_to_container")
        mocker.patch(f"{CLI}.container_exec")

        result = runner.invoke(app, ["sync", "myenv", "--yes", "--files", "main.py"])
        assert result.exit_code == 0
        assert "1 file(s)" in result.output

    def test_sync_nonexistent_file_errors(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        Path(meta.host_clone_path).mkdir(parents=True, exist_ok=True)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)

        result = runner.invoke(
            app, ["sync", "myenv", "--yes", "--files", "nonexistent.py"]
        )
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_sync_excludes_git(self, mocker, mock_trusty_cage_dir):
        from pathlib import Path

        from trusty_cage.environment import create_meta

        meta = create_meta(
            name="myenv", repo_url="https://a.com/r", auth_mode="api_key"
        )
        host_clone = Path(meta.host_clone_path)
        host_clone.mkdir(parents=True, exist_ok=True)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mock_rsync = mocker.patch(f"{CLI}.subprocess.run")
        mocker.patch(f"{CLI}.copy_to_container")
        mocker.patch(f"{CLI}.container_exec")

        result = runner.invoke(app, ["sync", "myenv", "--yes"])
        assert result.exit_code == 0

        rsync_cmd = mock_rsync.call_args[0][0]
        excludes = [
            rsync_cmd[i + 1]
            for i in range(len(rsync_cmd))
            if rsync_cmd[i] == "--exclude"
        ]
        assert ".git/" in excludes


class TestLaunchInjectMessaging:
    """Tests for --inject-messaging on launch command."""

    def test_inject_messaging_default(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="subscription")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mock_exec = mocker.patch(
            f"{CLI}.container_exec",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        )

        result = runner.invoke(app, ["launch", "myenv", "--prompt", "do stuff"])
        assert result.exit_code == 0

        cmd = mock_exec.call_args[0][1]
        bash_cmd = cmd[2]
        assert "cage-send" in bash_cmd
        assert "task_complete" in bash_cmd

    def test_no_inject_messaging(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="subscription")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mock_exec = mocker.patch(
            f"{CLI}.container_exec",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        )

        result = runner.invoke(
            app,
            ["launch", "myenv", "--prompt", "do stuff", "--no-inject-messaging"],
        )
        assert result.exit_code == 0

        cmd = mock_exec.call_args[0][1]
        bash_cmd = cmd[2]
        assert "cage-send" not in bash_cmd

    def test_inject_messaging_not_in_test_mode(self, mocker, mock_trusty_cage_dir):
        from trusty_cage.environment import create_meta

        create_meta(name="myenv", repo_url="https://a.com/r", auth_mode="subscription")
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mock_exec = mocker.patch(
            f"{CLI}.container_exec",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="claude 1.0.0", stderr=""
            ),
        )

        result = runner.invoke(app, ["launch", "myenv", "--test"])
        assert result.exit_code == 0
        cmd = mock_exec.call_args[0][1]
        assert cmd == ["claude", "--version"]


class TestDestroyWithAdditionalDirs:
    def test_destroy_removes_additional_volumes(self, mocker, mock_trusty_cage_dir):
        meta = create_meta(name="my-cage", repo_url="", auth_mode="api_key")
        dirs_path = get_env_dir("my-cage") / "dirs" / "shared-lib"
        dirs_path.mkdir(parents=True)
        meta.additional_dirs = [
            {
                "name": "shared-lib",
                "host_source_path": "/tmp/lib",
                "host_clone_path": str(dirs_path),
                "volume_name": "isolated-dev-my-cage-shared-lib",
                "container_path": "/home/trustycage/shared-lib",
                "added_at": "now",
            }
        ]
        save_meta(meta)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_exists", return_value=True)
        mocker.patch(f"{CLI}.container_remove")
        mocker.patch(f"{CLI}.volume_exists", return_value=True)
        mock_vol_remove = mocker.patch(f"{CLI}.volume_remove")

        result = runner.invoke(app, ["destroy", "my-cage", "--yes"])
        assert result.exit_code == 0

        vol_remove_calls = [call.args[0] for call in mock_vol_remove.call_args_list]
        assert "isolated-dev-my-cage" in vol_remove_calls
        assert "isolated-dev-my-cage-shared-lib" in vol_remove_calls

        assert not dirs_path.exists()


class TestListWithAdditionalDirs:
    def test_list_json_includes_additional_dirs(self, mocker, mock_trusty_cage_dir):
        meta = create_meta(name="my-cage", repo_url="", auth_mode="api_key")
        meta.additional_dirs = [
            {
                "name": "shared-lib",
                "host_source_path": "/tmp/lib",
                "host_clone_path": "/tmp/clone",
                "volume_name": "vol",
                "container_path": "/home/trustycage/shared-lib",
                "added_at": "now",
            }
        ]
        save_meta(meta)

        mocker.patch(f"{CLI}.container_exists", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=False)

        result = runner.invoke(app, ["list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["additional_dirs"] == ["shared-lib"]


class TestDiffWithDir:
    def test_diff_dir_not_found(self, mocker, mock_trusty_cage_dir):
        meta = create_meta(name="my-cage", repo_url="", auth_mode="api_key")
        save_meta(meta)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)

        result = runner.invoke(app, ["diff", "my-cage", "--dir", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_diff_with_dir_flag(self, mocker, mock_trusty_cage_dir, tmp_path):
        host_clone = tmp_path / "dirs" / "shared-lib"
        host_clone.mkdir(parents=True)

        meta = create_meta(name="my-cage", repo_url="", auth_mode="api_key")
        meta.additional_dirs = [
            {
                "name": "shared-lib",
                "host_source_path": "/tmp/shared-lib",
                "host_clone_path": str(host_clone),
                "volume_name": "isolated-dev-my-cage-shared-lib",
                "container_path": "/home/trustycage/shared-lib",
                "added_at": "now",
            }
        ]
        save_meta(meta)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mocker.patch(
            f"{CLI}.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        )

        result = runner.invoke(app, ["diff", "my-cage", "--dir", "shared-lib"])
        assert result.exit_code == 0


class TestSyncWithDir:
    def test_sync_dir_flag(self, mocker, mock_trusty_cage_dir, tmp_path):
        host_clone = tmp_path / "dirs" / "shared-lib"
        host_clone.mkdir(parents=True)
        (host_clone / "lib.py").write_text("# updated lib")

        meta = create_meta(name="my-cage", repo_url="", auth_mode="api_key")
        meta.additional_dirs = [
            {
                "name": "shared-lib",
                "host_source_path": "/tmp/shared-lib",
                "host_clone_path": str(host_clone),
                "volume_name": "isolated-dev-my-cage-shared-lib",
                "container_path": "/home/trustycage/shared-lib",
                "added_at": "now",
            }
        ]
        save_meta(meta)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_to_container")
        mocker.patch(f"{CLI}.container_exec")
        mocker.patch(
            f"{CLI}.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        )

        result = runner.invoke(app, ["sync", "my-cage", "--dir", "shared-lib", "--yes"])
        assert result.exit_code == 0
        assert "shared-lib" in result.output

    def test_sync_dir_not_found(self, mocker, mock_trusty_cage_dir):
        meta = create_meta(name="my-cage", repo_url="", auth_mode="api_key")
        save_meta(meta)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)

        result = runner.invoke(
            app, ["sync", "my-cage", "--dir", "nonexistent", "--yes"]
        )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestExportWithDir:
    def test_export_dir_not_found(self, mocker, mock_trusty_cage_dir):
        meta = create_meta(name="my-cage", repo_url="", auth_mode="api_key")
        save_meta(meta)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)

        result = runner.invoke(
            app, ["export", "my-cage", "--dir", "nonexistent", "--yes"]
        )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_export_with_dir_flag(self, mocker, mock_trusty_cage_dir, tmp_path):
        host_clone = tmp_path / "dirs" / "shared-lib"
        host_clone.mkdir(parents=True)

        meta = create_meta(name="my-cage", repo_url="", auth_mode="api_key")
        meta.additional_dirs = [
            {
                "name": "shared-lib",
                "host_source_path": "/tmp/shared-lib",
                "host_clone_path": str(host_clone),
                "volume_name": "isolated-dev-my-cage-shared-lib",
                "container_path": "/home/trustycage/shared-lib",
                "added_at": "now",
            }
        ]
        save_meta(meta)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_is_running", return_value=True)
        mocker.patch(f"{CLI}.copy_from_container")
        mocker.patch(
            f"{CLI}.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        )

        result = runner.invoke(
            app, ["export", "my-cage", "--dir", "shared-lib", "--yes"]
        )
        assert result.exit_code == 0
        assert "shared-lib" in result.output


class TestCreateWithAddDir:
    def test_create_with_add_dir_flag(self, mocker, mock_trusty_cage_dir, tmp_path):
        # Source dirs
        source_dir = tmp_path / "main-project"
        source_dir.mkdir()
        (source_dir / "main.py").write_text("# main")

        extra_dir = tmp_path / "shared-lib"
        extra_dir.mkdir()
        (extra_dir / "lib.py").write_text("# lib")

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.build_if_needed")
        mocker.patch(f"{CLI}.volume_create")
        mocker.patch(f"{CLI}.volume_exists", return_value=False)
        mocker.patch(f"{CLI}.container_create")
        mocker.patch(f"{CLI}.container_start")
        mocker.patch(f"{CLI}.copy_to_container")
        mocker.patch(f"{CLI}.container_exec")
        mocker.patch(f"{CLI}.init_messaging_dirs")
        mocker.patch(f"{CLI}.container_is_running", return_value=True)

        result = runner.invoke(
            app,
            [
                "create",
                "--dir",
                str(source_dir),
                "--no-attach",
                "--auth-mode",
                "api_key",
                "--add-dir",
                str(extra_dir),
            ],
        )
        assert result.exit_code == 0

        # Verify meta has the additional dir
        loaded = load_meta("main-project")
        assert len(loaded.additional_dirs) == 1
        assert loaded.additional_dirs[0]["name"] == "shared-lib"


class TestAddDirCommand:
    def test_fails_when_docker_not_running(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=False)
        result = runner.invoke(app, ["add-dir", "my-cage", "/tmp/somedir"])
        assert result.exit_code != 0
        assert "Docker" in result.output

    def test_fails_when_env_not_found(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(app, ["add-dir", "nonexistent", "/tmp/somedir"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_fails_when_dir_does_not_exist(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.env_exists", return_value=True)
        mocker.patch(
            f"{CLI}.load_meta",
            return_value=MetaJson(
                name="my-cage",
                repo_url="",
                created_at="now",
                volume_name="isolated-dev-my-cage",
                container_name="isolated-dev-my-cage",
                host_clone_path="/tmp/repo",
                auth_mode="api_key",
            ),
        )
        result = runner.invoke(app, ["add-dir", "my-cage", "/nonexistent/path"])
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_fails_on_name_collision_with_project(
        self, mocker, mock_trusty_cage_dir, tmp_path
    ):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.env_exists", return_value=True)
        mocker.patch(
            f"{CLI}.load_meta",
            return_value=MetaJson(
                name="my-cage",
                repo_url="",
                created_at="now",
                volume_name="isolated-dev-my-cage",
                container_name="isolated-dev-my-cage",
                host_clone_path="/tmp/repo",
                auth_mode="api_key",
            ),
        )
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        result = runner.invoke(app, ["add-dir", "my-cage", str(project_dir)])
        assert result.exit_code != 0
        assert "project" in result.output.lower()

    def test_fails_on_duplicate_dir_name(self, mocker, mock_trusty_cage_dir, tmp_path):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.env_exists", return_value=True)
        meta = MetaJson(
            name="my-cage",
            repo_url="",
            created_at="now",
            volume_name="isolated-dev-my-cage",
            container_name="isolated-dev-my-cage",
            host_clone_path="/tmp/repo",
            auth_mode="api_key",
            additional_dirs=[
                {
                    "name": "shared-lib",
                    "host_source_path": "/tmp/lib",
                    "host_clone_path": "/tmp/clone",
                    "volume_name": "vol",
                    "container_path": "/home/trustycage/shared-lib",
                    "added_at": "now",
                }
            ],
        )
        mocker.patch(f"{CLI}.load_meta", return_value=meta)
        lib_dir = tmp_path / "shared-lib"
        lib_dir.mkdir()
        result = runner.invoke(app, ["add-dir", "my-cage", str(lib_dir)])
        assert result.exit_code != 0
        assert "already exists" in result.output.lower()

    def test_successful_add_dir(self, mocker, mock_trusty_cage_dir, tmp_path):
        # Create source dir with a file
        source = tmp_path / "shared-lib"
        source.mkdir()
        (source / "lib.py").write_text("# lib")

        # Create meta on disk so save_meta works
        create_meta(
            name="my-cage",
            repo_url="https://github.com/user/repo",
            auth_mode="api_key",
        )

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.volume_create")
        mocker.patch(f"{CLI}.volume_exists", return_value=False)
        mocker.patch(f"{CLI}.container_recreate")
        mocker.patch(f"{CLI}.copy_to_container")
        mocker.patch(f"{CLI}.container_exec")
        mocker.patch(f"{CLI}.container_is_running", return_value=True)

        result = runner.invoke(app, ["add-dir", "my-cage", str(source)])
        assert result.exit_code == 0
        assert "added" in result.output.lower()

        # Verify meta was updated
        loaded = load_meta("my-cage")
        assert len(loaded.additional_dirs) == 1
        assert loaded.additional_dirs[0]["name"] == "shared-lib"


class TestRemoveDirCommand:
    def test_fails_when_env_not_found(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        result = runner.invoke(app, ["remove-dir", "nonexistent", "shared-lib"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_fails_when_dir_not_in_meta(self, mocker, mock_trusty_cage_dir):
        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.env_exists", return_value=True)
        mocker.patch(
            f"{CLI}.load_meta",
            return_value=MetaJson(
                name="my-cage",
                repo_url="",
                created_at="now",
                volume_name="isolated-dev-my-cage",
                container_name="isolated-dev-my-cage",
                host_clone_path="/tmp/repo",
                auth_mode="api_key",
            ),
        )
        result = runner.invoke(app, ["remove-dir", "my-cage", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_successful_remove_dir(self, mocker, mock_trusty_cage_dir):
        meta = create_meta(
            name="my-cage",
            repo_url="https://github.com/user/repo",
            auth_mode="api_key",
        )
        dirs_path = get_env_dir("my-cage") / "dirs" / "shared-lib"
        dirs_path.mkdir(parents=True)
        dir_entry = {
            "name": "shared-lib",
            "host_source_path": "/tmp/shared-lib",
            "host_clone_path": str(dirs_path),
            "volume_name": "isolated-dev-my-cage-shared-lib",
            "container_path": "/home/trustycage/shared-lib",
            "added_at": "2026-03-30T12:00:00+00:00",
        }
        meta.additional_dirs = [dir_entry]
        save_meta(meta)

        mocker.patch(f"{CLI}.is_docker_running", return_value=True)
        mocker.patch(f"{CLI}.container_recreate")
        mocker.patch(f"{CLI}.container_exec")
        mocker.patch(f"{CLI}.volume_exists", return_value=True)
        mocker.patch(f"{CLI}.volume_remove")
        mocker.patch(f"{CLI}.container_is_running", return_value=True)

        result = runner.invoke(app, ["remove-dir", "my-cage", "shared-lib", "--yes"])
        assert result.exit_code == 0
        assert "removed" in result.output.lower()

        loaded = load_meta("my-cage")
        assert len(loaded.additional_dirs) == 0
