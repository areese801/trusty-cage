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


class TestGitignoreAwareStats:
    """Regression suite: stats must not count files ignored by .gitignore
    or the trusty-cage default cache patterns (motivated by cage runs where
    27MB of .mypy_cache pollution inflated the reported count by 200×)."""

    def _dirs(self, tmp_path):
        before = tmp_path / "before"
        after = tmp_path / "after"
        before.mkdir()
        after.mkdir()
        return before, after

    def test_cache_dir_is_not_counted(self, mocker, tmp_path):
        """.mypy_cache/ is in DEFAULT_CACHE_PATTERNS; stats must skip it."""
        mocker.patch("trusty_cage.stats.shutil.which", return_value=None)
        before, after = self._dirs(tmp_path)
        # Real deliverable: 2 lines in app.py
        (after / "app.py").write_text("a\nb\n")
        # Noise: 1000 lines in .mypy_cache/
        cache = after / ".mypy_cache"
        cache.mkdir()
        (cache / "junk.txt").write_text("\n".join(str(i) for i in range(1000)) + "\n")

        stats, _used_cloc = compute_stats(before, after)
        total = sum(s.lines_added for s in stats)
        assert total == 2, f"stats should ignore .mypy_cache contents, got {stats}"

    def test_gitignore_entry_excluded(self, mocker, tmp_path):
        """A 1000-line file ignored by .gitignore should not be counted."""
        mocker.patch("trusty_cage.stats.shutil.which", return_value=None)
        before, after = self._dirs(tmp_path)
        (after / ".gitignore").write_text("generated.txt\n")
        (after / "app.py").write_text("x\n")
        (after / "generated.txt").write_text(
            "\n".join(str(i) for i in range(1000)) + "\n"
        )

        stats, _ = compute_stats(before, after)
        # Only the app.py addition (1 line) + the .gitignore itself should count
        total = sum(s.lines_added for s in stats)
        assert total < 10, (
            f"stats should ignore 'generated.txt' (in .gitignore), got {total}"
        )

    def test_untracked_non_ignored_file_counted(self, mocker, tmp_path):
        """A normal file not matching any ignore pattern must still count."""
        mocker.patch("trusty_cage.stats.shutil.which", return_value=None)
        before, after = self._dirs(tmp_path)
        (after / ".gitignore").write_text("build/\n")
        (after / "app.py").write_text("line1\nline2\nline3\n")

        stats, _ = compute_stats(before, after)
        py = [s for s in stats if s.language == "Python"]
        assert py and py[0].lines_added == 3

    def test_ignored_on_one_side_union_semantics(self, mocker, tmp_path):
        """If .gitignore on either side ignores a path, stats must skip it."""
        mocker.patch("trusty_cage.stats.shutil.which", return_value=None)
        before, after = self._dirs(tmp_path)
        # Only the BEFORE side has a .gitignore mentioning secret.txt
        (before / ".gitignore").write_text("secret.txt\n")
        (before / "app.py").write_text("a\n")
        (after / "app.py").write_text("a\nb\n")
        # secret.txt appears on after with many lines — should still be ignored
        (after / "secret.txt").write_text("\n".join("x" for _ in range(200)) + "\n")

        stats, _ = compute_stats(before, after)
        total_added = sum(s.lines_added for s in stats)
        # Only the 1-line addition to app.py should count
        assert total_added <= 2, (
            f"ignored on before-side should still exclude secret.txt, got {total_added}"
        )

    def test_include_cache_true_counts_caches(self, mocker, tmp_path):
        """include_cache=True should bring .mypy_cache back into the count."""
        mocker.patch("trusty_cage.stats.shutil.which", return_value=None)
        before, after = self._dirs(tmp_path)
        cache = after / ".mypy_cache"
        cache.mkdir()
        (cache / "junk.txt").write_text("a\nb\nc\n")

        stats, _ = compute_stats(before, after, include_cache=True)
        total = sum(s.lines_added for s in stats)
        assert total >= 3, f"include_cache=True should count cache dirs, got {total}"
