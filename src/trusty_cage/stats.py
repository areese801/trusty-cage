"""
Code statistics for comparing directories before and after cage work.

Uses cloc (if installed) for language-aware stats, with a pure-Python
fallback based on difflib and file extension mapping.

Both paths honor ``.gitignore`` and the trusty-cage default cache patterns
(``.mypy_cache/``, ``.pytest_cache/`` etc.) so stats don't get wildly
inflated by transient build artifacts.
"""

import difflib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pathspec
from rich import print as rprint
from rich.table import Table

from trusty_cage import ignore


@dataclass
class LanguageStats:
    """
    Per-language line change statistics.
    """

    language: str
    files_changed: int
    lines_added: int
    lines_removed: int
    lines_modified: int


EXTENSION_MAP: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".rb": "Ruby",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".cs": "C#",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".sql": "SQL",
    ".r": "R",
    ".R": "R",
    ".md": "Markdown",
    ".html": "HTML",
    ".css": "CSS",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
}


def _language_for_file(path: Path) -> str:
    """
    Determine language from file extension.
    """
    return EXTENSION_MAP.get(path.suffix, "Other")


def _collect_files(
    directory: Path,
    spec: pathspec.PathSpec | None = None,
) -> dict[str, list[str]]:
    """
    Walk a directory and return {relative_path: lines} for text files.
    Skips .git/, binary files, and unreadable files.

    When ``spec`` is provided, any path that matches the spec is skipped —
    use this to filter out gitignored files and cache directories.
    """
    result: dict[str, list[str]] = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(directory))
        if rel.startswith(".git/") or rel == ".git":
            continue
        if spec is not None and spec.match_file(rel):
            continue
        try:
            lines = path.read_text().splitlines()
            result[rel] = lines
        except (UnicodeDecodeError, PermissionError):
            continue
    return result


def _cloc_stats(
    before: Path,
    after: Path,
    exclude_dirs: list[str] | None = None,
) -> list[LanguageStats] | None:
    """
    Run cloc --diff --json and parse the results.
    Returns None if cloc fails.

    ``exclude_dirs`` is passed to cloc as ``--exclude-dir``. Cloc does
    not read .gitignore itself, so the caller is responsible for deriving
    a sensible list (typically cache-dir basenames plus simple directory
    names from .gitignore).
    """
    cmd = ["cloc", "--diff", "--json"]
    if exclude_dirs:
        cmd.append(f"--exclude-dir={','.join(sorted(set(exclude_dirs)))}")
    cmd.extend([str(before), str(after)])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        return None

    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None

    # Aggregate per-language stats from cloc's added/removed/modified sections
    languages: dict[str, LanguageStats] = {}

    for section, field in [
        ("added", "lines_added"),
        ("removed", "lines_removed"),
        ("modified", "lines_modified"),
    ]:
        section_data = data.get(section, {})
        for lang, counts in section_data.items():
            if lang in ("header", "SUM"):
                continue
            if lang not in languages:
                languages[lang] = LanguageStats(
                    language=lang,
                    files_changed=0,
                    lines_added=0,
                    lines_removed=0,
                    lines_modified=0,
                )
            setattr(languages[lang], field, counts.get("code", 0))
            # Track files changed (take max across sections to avoid double-counting)
            current = languages[lang].files_changed
            languages[lang].files_changed = max(current, counts.get("nFiles", 0))

    stats = sorted(languages.values(), key=lambda s: s.language)
    return [s for s in stats if s.lines_added or s.lines_removed or s.lines_modified]


def _fallback_stats(
    before: Path,
    after: Path,
    spec: pathspec.PathSpec | None = None,
) -> list[LanguageStats]:
    """
    Pure-Python line diff stats using difflib.

    ``spec`` is applied to both sides — a path matching the spec in either
    tree is skipped.
    """
    before_files = _collect_files(before, spec=spec)
    after_files = _collect_files(after, spec=spec)

    all_paths = sorted(set(before_files.keys()) | set(after_files.keys()))

    # Per-language accumulators
    accum: dict[str, LanguageStats] = {}

    for rel in all_paths:
        lang = _language_for_file(Path(rel))
        if lang not in accum:
            accum[lang] = LanguageStats(
                language=lang,
                files_changed=0,
                lines_added=0,
                lines_removed=0,
                lines_modified=0,
            )

        before_lines = before_files.get(rel, [])
        after_lines = after_files.get(rel, [])

        if before_lines == after_lines:
            continue

        accum[lang].files_changed += 1

        if rel not in before_files:
            # New file — all lines added
            accum[lang].lines_added += len(after_lines)
        elif rel not in after_files:
            # Deleted file — all lines removed
            accum[lang].lines_removed += len(before_lines)
        else:
            # Modified file — count diff lines
            diff = list(difflib.unified_diff(before_lines, after_lines, lineterm=""))
            for line in diff:
                if line.startswith("+++") or line.startswith("---"):
                    continue
                if line.startswith("+"):
                    accum[lang].lines_added += 1
                elif line.startswith("-"):
                    accum[lang].lines_removed += 1

    stats = sorted(accum.values(), key=lambda s: s.language)
    return [s for s in stats if s.lines_added or s.lines_removed or s.lines_modified]


def compute_stats(
    before: Path,
    after: Path,
    include_cache: bool = False,
) -> tuple[list[LanguageStats], bool]:
    """
    Compute per-language line change statistics between two directories.

    Honors ``.gitignore`` and the trusty-cage default cache patterns from
    ``ignore.DEFAULT_CACHE_PATTERNS`` unless ``include_cache`` is True.
    A file ignored by either side's rules is excluded from both sides so
    stats don't count files that one side considers transient.

    Returns (stats_list, used_cloc) where used_cloc indicates whether
    cloc was used (True) or the fallback counter (False).
    """
    spec = ignore.build_union_pathspec([before, after], include_cache=include_cache)

    if shutil.which("cloc"):
        # cloc doesn't read .gitignore; hand it directory basenames we can
        # extract. Covers the cache dirs and simple name-only gitignore
        # entries — which is most of what causes stats noise in practice.
        exclude_dirs = list(ignore.DEFAULT_CACHE_PATTERNS) if not include_cache else []
        exclude_dirs.extend(ignore.read_gitignore_lines(before))
        exclude_dirs.extend(ignore.read_gitignore_lines(after))
        exclude_dir_basenames = ignore.directory_basenames_from_patterns(exclude_dirs)
        result = _cloc_stats(before, after, exclude_dirs=exclude_dir_basenames)
        if result is not None:
            return result, True

    return _fallback_stats(before, after, spec=spec), False


def render_stats_table(stats: list[LanguageStats], used_cloc: bool) -> None:
    """
    Render a Rich table of language stats.
    """
    if not stats:
        return

    table = Table(title="Code Statistics", show_header=True, header_style="bold")
    table.add_column("Language")
    table.add_column("Files", justify="right")
    table.add_column("Added", justify="right", style="green")
    table.add_column("Removed", justify="right", style="red")
    if used_cloc:
        table.add_column("Modified", justify="right", style="yellow")

    total_files = 0
    total_added = 0
    total_removed = 0
    total_modified = 0

    for s in stats:
        row = [
            s.language,
            str(s.files_changed),
            f"+{s.lines_added}",
            f"-{s.lines_removed}",
        ]
        if used_cloc:
            row.append(f"~{s.lines_modified}")
        table.add_row(*row)
        total_files += s.files_changed
        total_added += s.lines_added
        total_removed += s.lines_removed
        total_modified += s.lines_modified

    # Totals row
    table.add_section()
    totals = [
        "[bold]Total[/bold]",
        f"[bold]{total_files}[/bold]",
        f"[bold green]+{total_added}[/bold green]",
        f"[bold red]-{total_removed}[/bold red]",
    ]
    if used_cloc:
        totals.append(f"[bold yellow]~{total_modified}[/bold yellow]")
    table.add_row(*totals)

    rprint(table)

    if used_cloc:
        rprint("[dim](via cloc)[/dim]")
    else:
        rprint("[dim](install cloc for language-aware stats)[/dim]")
