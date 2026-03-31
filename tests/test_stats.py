"""
Tests for stats module.
"""

import json
import subprocess

from trusty_cage.stats import (
    LanguageStats,
    _collect_files,
    _fallback_stats,
    _language_for_file,
    compute_stats,
    render_stats_table,
)
from pathlib import Path


class TestLanguageForFile:
    def test_python(self):
        assert _language_for_file(Path("app.py")) == "Python"

    def test_javascript(self):
        assert _language_for_file(Path("index.js")) == "JavaScript"

    def test_typescript(self):
        assert _language_for_file(Path("app.tsx")) == "TypeScript"

    def test_unknown_extension(self):
        assert _language_for_file(Path("file.xyz")) == "Other"

    def test_no_extension(self):
        assert _language_for_file(Path("Makefile")) == "Other"


class TestCollectFiles:
    def test_collects_text_files(self, tmp_path):
        (tmp_path / "app.py").write_text("line1\nline2\n")
        (tmp_path / "lib.py").write_text("a\nb\nc\n")
        result = _collect_files(tmp_path)
        assert "app.py" in result
        assert result["app.py"] == ["line1", "line2"]
        assert len(result["lib.py"]) == 3

    def test_skips_git_directory(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("gitconfig")
        (tmp_path / "app.py").write_text("code")
        result = _collect_files(tmp_path)
        assert "app.py" in result
        assert ".git/config" not in result

    def test_skips_binary_files(self, tmp_path):
        (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
        (tmp_path / "app.py").write_text("code")
        result = _collect_files(tmp_path)
        assert "app.py" in result
        assert "image.png" not in result

    def test_handles_subdirectories(self, tmp_path):
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "main.py").write_text("main")
        result = _collect_files(tmp_path)
        assert "src/main.py" in result


class TestFallbackStats:
    def test_new_files(self, tmp_path):
        before = tmp_path / "before"
        after = tmp_path / "after"
        before.mkdir()
        after.mkdir()
        (after / "app.py").write_text("line1\nline2\nline3\n")
        stats = _fallback_stats(before, after)
        assert len(stats) == 1
        assert stats[0].language == "Python"
        assert stats[0].lines_added == 3
        assert stats[0].lines_removed == 0
        assert stats[0].files_changed == 1

    def test_deleted_files(self, tmp_path):
        before = tmp_path / "before"
        after = tmp_path / "after"
        before.mkdir()
        after.mkdir()
        (before / "old.py").write_text("gone1\ngone2\n")
        stats = _fallback_stats(before, after)
        assert len(stats) == 1
        assert stats[0].lines_removed == 2
        assert stats[0].lines_added == 0

    def test_modified_files(self, tmp_path):
        before = tmp_path / "before"
        after = tmp_path / "after"
        before.mkdir()
        after.mkdir()
        (before / "app.py").write_text("old_line\n")
        (after / "app.py").write_text("new_line\nextra_line\n")
        stats = _fallback_stats(before, after)
        assert len(stats) == 1
        assert stats[0].lines_added >= 1
        assert stats[0].lines_removed >= 1

    def test_no_changes(self, tmp_path):
        before = tmp_path / "before"
        after = tmp_path / "after"
        before.mkdir()
        after.mkdir()
        (before / "app.py").write_text("same\n")
        (after / "app.py").write_text("same\n")
        stats = _fallback_stats(before, after)
        assert stats == []

    def test_multiple_languages(self, tmp_path):
        before = tmp_path / "before"
        after = tmp_path / "after"
        before.mkdir()
        after.mkdir()
        (after / "app.py").write_text("python\n")
        (after / "index.js").write_text("javascript\n")
        stats = _fallback_stats(before, after)
        assert len(stats) == 2
        languages = {s.language for s in stats}
        assert "Python" in languages
        assert "JavaScript" in languages


class TestComputeStats:
    def test_uses_cloc_when_available(self, mocker, tmp_path):
        mocker.patch("trusty_cage.stats.shutil.which", return_value="/usr/bin/cloc")
        cloc_output = json.dumps(
            {
                "header": {},
                "added": {
                    "Python": {"nFiles": 1, "blank": 0, "comment": 0, "code": 10}
                },
                "removed": {},
                "modified": {},
                "same": {},
                "SUM": {},
            }
        )
        mocker.patch(
            "trusty_cage.stats.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=cloc_output, stderr=""
            ),
        )
        before = tmp_path / "before"
        after = tmp_path / "after"
        before.mkdir()
        after.mkdir()
        stats, used_cloc = compute_stats(before, after)
        assert used_cloc is True
        assert len(stats) == 1
        assert stats[0].language == "Python"
        assert stats[0].lines_added == 10

    def test_falls_back_when_no_cloc(self, mocker, tmp_path):
        mocker.patch("trusty_cage.stats.shutil.which", return_value=None)
        before = tmp_path / "before"
        after = tmp_path / "after"
        before.mkdir()
        after.mkdir()
        (after / "app.py").write_text("code\n")
        stats, used_cloc = compute_stats(before, after)
        assert used_cloc is False
        assert len(stats) == 1

    def test_falls_back_when_cloc_fails(self, mocker, tmp_path):
        mocker.patch("trusty_cage.stats.shutil.which", return_value="/usr/bin/cloc")
        mocker.patch(
            "trusty_cage.stats.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "cloc"),
        )
        before = tmp_path / "before"
        after = tmp_path / "after"
        before.mkdir()
        after.mkdir()
        (after / "app.py").write_text("code\n")
        stats, used_cloc = compute_stats(before, after)
        assert used_cloc is False


class TestRenderStatsTable:
    def test_renders_without_error(self, capsys):
        stats = [
            LanguageStats(
                language="Python",
                files_changed=3,
                lines_added=100,
                lines_removed=20,
                lines_modified=5,
            )
        ]
        render_stats_table(stats, used_cloc=True)
        output = capsys.readouterr().out
        assert "Python" in output
        assert "100" in output

    def test_empty_stats_renders_nothing(self, capsys):
        render_stats_table([], used_cloc=False)
        output = capsys.readouterr().out
        assert output == ""

    def test_fallback_note(self, capsys):
        stats = [
            LanguageStats(
                language="Python",
                files_changed=1,
                lines_added=5,
                lines_removed=0,
                lines_modified=0,
            )
        ]
        render_stats_table(stats, used_cloc=False)
        output = capsys.readouterr().out
        assert "install cloc" in output

    def test_cloc_note(self, capsys):
        stats = [
            LanguageStats(
                language="Python",
                files_changed=1,
                lines_added=5,
                lines_removed=0,
                lines_modified=0,
            )
        ]
        render_stats_table(stats, used_cloc=True)
        output = capsys.readouterr().out
        assert "via cloc" in output
