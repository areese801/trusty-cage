"""
Shared ignore-pattern logic.

One source of truth for:
- The default cache patterns ``tc export`` / ``tc diff`` / ``tc tidy`` treat
  as transient build artifacts (e.g. ``.mypy_cache/``).
- Reading a repo-local ``.gitignore`` / ``.cageprotect`` file.
- Building a ``pathspec.PathSpec`` that can be consulted while walking a
  directory tree, so stats / tidy can skip files that git would ignore.
"""

from pathlib import Path
from typing import Iterable

import pathspec


DEFAULT_CACHE_PATTERNS: tuple[str, ...] = (
    "__pycache__/",
    "*.py[cod]",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".DS_Store",
    "node_modules/",
)


def _read_non_comment_lines(path: Path) -> list[str]:
    """
    Read a file and return non-blank, non-comment stripped lines.
    Missing file returns an empty list.
    """
    if not path.is_file():
        return []
    out: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def read_gitignore_lines(root: Path) -> list[str]:
    """
    Read ``<root>/.gitignore`` and return its non-comment, non-blank lines.
    """
    return _read_non_comment_lines(root / ".gitignore")


def read_cageprotect_lines(root: Path) -> list[str]:
    """
    Read ``<root>/.cageprotect`` and return its non-comment, non-blank lines.
    """
    return _read_non_comment_lines(root / ".cageprotect")


def build_rsync_exclude_patterns(
    root: Path,
    extra: Iterable[str] = (),
    include_cache: bool = False,
) -> list[str]:
    """
    Build a deduplicated, ordered list of rsync ``--exclude`` patterns.

    Always includes ``.git/``, ``.cageprotect``, ``venv/``, ``.venv/``.
    When ``include_cache`` is False (the default), also adds
    ``DEFAULT_CACHE_PATTERNS``. Lines from ``<root>/.gitignore`` and
    ``<root>/.cageprotect`` are appended, followed by any ``extra`` patterns.

    Note: rsync's pattern syntax is glob-like, not a full gitignore
    implementation — but for the common directory/file patterns this
    gives roughly the right behavior for ``tc export`` / ``tc diff``.
    """
    seen: set[str] = set()
    patterns: list[str] = []

    def add(p: str) -> None:
        if p not in seen:
            seen.add(p)
            patterns.append(p)

    add(".git/")
    add(".cageprotect")
    add("venv/")
    add(".venv/")

    if not include_cache:
        for p in DEFAULT_CACHE_PATTERNS:
            add(p)

    for line in read_gitignore_lines(root):
        add(line)
    for line in read_cageprotect_lines(root):
        add(line)

    for p in extra:
        add(p)

    return patterns


def build_pathspec(
    root: Path,
    include_cache: bool = False,
) -> pathspec.PathSpec:
    """
    Build a PathSpec using git's wildmatch rules from ``<root>/.gitignore``,
    plus the trusty-cage defaults (``.git/`` always, and the cache patterns
    unless ``include_cache`` is True).

    Use this when walking a directory and filtering entries that should
    be treated as "not part of the work" (stats, tidy).
    """
    lines: list[str] = [".git/"]
    if not include_cache:
        lines.extend(DEFAULT_CACHE_PATTERNS)
    lines.extend(read_gitignore_lines(root))
    return pathspec.PathSpec.from_lines("gitignore", lines)


def build_union_pathspec(
    roots: Iterable[Path],
    include_cache: bool = False,
) -> pathspec.PathSpec:
    """
    Build a single PathSpec that unions the ignore rules from multiple roots.

    A file is ignored if any root's rules would ignore it. Useful for
    comparing two trees where either side may contain a ``.gitignore`` —
    e.g. the host clone and the cage's exported working tree.
    """
    lines: list[str] = [".git/"]
    if not include_cache:
        lines.extend(DEFAULT_CACHE_PATTERNS)
    for root in roots:
        lines.extend(read_gitignore_lines(root))
    return pathspec.PathSpec.from_lines("gitignore", lines)


def directory_basenames_from_patterns(patterns: Iterable[str]) -> list[str]:
    """
    Extract directory basenames from a list of gitignore-style patterns.

    Returns entries that look like ``name/`` or ``name`` (simple directory
    references with no path separators or wildcards in the basename portion).
    Used to hand cloc ``--exclude-dir`` a list it can act on, since cloc
    does not read ``.gitignore``.
    """
    names: list[str] = []
    for raw in patterns:
        p = raw.rstrip("/")
        if not p or "/" in p or "*" in p or "?" in p or "[" in p:
            continue
        if p.startswith("!"):
            continue
        names.append(p)
    return names
