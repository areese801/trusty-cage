"""
Tests for the ignore module (shared gitignore / cache / pathspec helpers).
"""

from pathlib import Path

from trusty_cage import ignore


class TestReadGitignoreLines:
    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert ignore.read_gitignore_lines(tmp_path) == []

    def test_reads_non_blank_non_comment_lines(self, tmp_path: Path):
        (tmp_path / ".gitignore").write_text(
            "# comment\n\nbuild/\n   \n*.log\n# another comment\nnode_modules/\n"
        )
        assert ignore.read_gitignore_lines(tmp_path) == [
            "build/",
            "*.log",
            "node_modules/",
        ]


class TestBuildRsyncExcludePatterns:
    def test_defaults_include_cache_patterns(self, tmp_path: Path):
        patterns = ignore.build_rsync_exclude_patterns(tmp_path)
        assert ".git/" in patterns
        assert ".mypy_cache/" in patterns
        assert "__pycache__/" in patterns

    def test_include_cache_true_omits_cache_patterns(self, tmp_path: Path):
        patterns = ignore.build_rsync_exclude_patterns(tmp_path, include_cache=True)
        assert ".git/" in patterns
        assert ".mypy_cache/" not in patterns
        assert "__pycache__/" not in patterns

    def test_reads_gitignore_and_cageprotect(self, tmp_path: Path):
        (tmp_path / ".gitignore").write_text("build/\nfoo.secret\n")
        (tmp_path / ".cageprotect").write_text("keep-this.txt\n")
        patterns = ignore.build_rsync_exclude_patterns(tmp_path)
        assert "build/" in patterns
        assert "foo.secret" in patterns
        assert "keep-this.txt" in patterns

    def test_extra_patterns_appended_deduplicated(self, tmp_path: Path):
        patterns = ignore.build_rsync_exclude_patterns(
            tmp_path,
            extra=["*.tmp", ".git/"],  # dedup: .git/ already present
        )
        assert patterns.count(".git/") == 1
        assert "*.tmp" in patterns


class TestBuildPathspec:
    def test_default_pathspec_matches_cache_dirs(self, tmp_path: Path):
        spec = ignore.build_pathspec(tmp_path)
        assert spec.match_file(".mypy_cache/a.py") is True
        assert spec.match_file("src/app.py") is False

    def test_include_cache_true_does_not_match_cache(self, tmp_path: Path):
        spec = ignore.build_pathspec(tmp_path, include_cache=True)
        assert spec.match_file(".mypy_cache/a.py") is False

    def test_pathspec_reads_gitignore(self, tmp_path: Path):
        (tmp_path / ".gitignore").write_text("dist/\n*.log\n")
        spec = ignore.build_pathspec(tmp_path)
        assert spec.match_file("dist/app.tar") is True
        assert spec.match_file("server.log") is True
        assert spec.match_file("server.py") is False


class TestBuildUnionPathspec:
    def test_union_takes_rules_from_both_roots(self, tmp_path: Path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        (a / ".gitignore").write_text("only-in-a.txt\n")
        (b / ".gitignore").write_text("only-in-b.txt\n")

        spec = ignore.build_union_pathspec([a, b])
        assert spec.match_file("only-in-a.txt") is True
        assert spec.match_file("only-in-b.txt") is True
        assert spec.match_file("something-else.py") is False


class TestDirectoryBasenames:
    def test_extracts_simple_dir_names(self):
        names = ignore.directory_basenames_from_patterns(
            ["build/", "dist", ".mypy_cache/", "src/foo/", "*.log", "!keep.txt"]
        )
        assert "build" in names
        assert "dist" in names
        assert ".mypy_cache" in names
        # Paths with separators are not directory basenames
        assert "src/foo" not in names
        # Wildcards are not directory basenames
        assert "*.log" not in names
        # Negations are not directory basenames
        assert "!keep.txt" not in names
