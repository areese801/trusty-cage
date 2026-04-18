"""
Diagnostic sweep for a cage environment.

Inspects the inner Claude process state, outbox activity, inside-cage git
status, and stream-log tail, then returns a structured report. Used by
`tc diagnose` and automatically on `tc outbox --poll` timeout to help the
operator decide whether to salvage, re-launch, or keep waiting.
"""

import json
from dataclasses import asdict, dataclass
from typing import Any, Optional

from trusty_cage import constants
from trusty_cage.docker import container_exec, container_exists, container_is_running


@dataclass
class ProcessState:
    """
    State of the inner `claude` process inside the container.

    state is one of:
      - "alive"   — process is running (any non-zombie state)
      - "zombie"  — process is <defunct> (parent never reaped it)
      - "absent"  — no claude process found
      - "unknown" — could not determine (e.g., container stopped)
    """

    state: str
    pid: Optional[int] = None
    cmdline: str = ""


@dataclass
class OutboxSummary:
    """
    Summary of the cage's outbox directory.
    """

    count: int = 0
    last_type: Optional[str] = None
    last_timestamp: Optional[str] = None
    last_filename: Optional[str] = None


@dataclass
class GitSummary:
    """
    Summary of the cage's inside-container project git state.
    """

    available: bool = False
    short_status: str = ""
    last_commit: Optional[str] = None
    modified_count: int = 0
    untracked_count: int = 0


@dataclass
class DiagnosticReport:
    """
    Full diagnostic report for a cage environment.
    """

    env_name: str
    container_name: str
    container_exists: bool
    container_running: bool
    process: ProcessState
    outbox: OutboxSummary
    git: GitSummary
    stream_tail: str = ""
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        """
        Return a plain dict suitable for JSON serialization.
        """
        return asdict(self)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _is_claude_command(args: str) -> bool:
    """
    Return True if `args` is the command line of the inner claude process.

    Matches the executable (first token), not any occurrence of "claude" in
    the full args string — avoids false positives like `tail -f claude-stream.log`
    or `grep claude`.

    Two shapes are recognized:
      1. `claude ...` or `/path/to/claude ...` — the native launch
      2. `node /path/to/claude-code/cli.js ...` — the current Node-based launch
    """
    first = args.split(None, 1)[0] if args else ""
    basename = first.rsplit("/", 1)[-1]

    if basename == "claude":
        return True
    if basename in ("node", "nodejs") and "claude-code" in args:
        return True
    return False


def check_process(container_name: str) -> ProcessState:
    """
    Inspect the `claude` process inside the container.

    Uses `ps` rather than `pgrep` so we can detect zombie (<defunct>) state.
    """
    result = container_exec(
        container_name,
        ["ps", "-eo", "pid,stat,args", "--no-headers"],
        user="root",
        check=False,
    )
    if result.returncode != 0:
        return ProcessState(state="unknown", cmdline=(result.stderr or "").strip())

    matches: list[tuple[int, str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid_s, stat, args = parts
        if not _is_claude_command(args):
            continue
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        matches.append((pid, stat, args))

    if not matches:
        return ProcessState(state="absent")

    for pid, stat, args in matches:
        if stat.startswith("Z"):
            return ProcessState(state="zombie", pid=pid, cmdline=args[:200])

    pid, _stat, args = matches[0]
    return ProcessState(state="alive", pid=pid, cmdline=args[:200])


def check_outbox(container_name: str) -> OutboxSummary:
    """
    Summarize the cage's outbox: total count and most recent message.
    """
    ls = container_exec(
        container_name,
        [
            "bash",
            "-c",
            f"ls -1 {constants.CAGE_OUTBOX_DIR}/*.json 2>/dev/null | sort",
        ],
        user=constants.CONTAINER_USER,
        check=False,
    )
    if ls.returncode != 0 or not ls.stdout.strip():
        return OutboxSummary(count=0)

    files = [f for f in ls.stdout.strip().splitlines() if f.endswith(".json")]
    if not files:
        return OutboxSummary(count=0)

    last_path = files[-1]
    last_filename = last_path.rsplit("/", 1)[-1]

    cat = container_exec(
        container_name,
        ["cat", last_path],
        user=constants.CONTAINER_USER,
        check=False,
    )
    last_type: Optional[str] = None
    last_timestamp: Optional[str] = None
    if cat.returncode == 0:
        try:
            data = json.loads(cat.stdout)
            last_type = data.get("type")
            last_timestamp = data.get("timestamp")
        except (json.JSONDecodeError, TypeError):
            pass

    return OutboxSummary(
        count=len(files),
        last_type=last_type,
        last_timestamp=last_timestamp,
        last_filename=last_filename,
    )


def check_git(container_name: str) -> GitSummary:
    """
    Inspect the inside-container project git state.
    """
    project_dir = constants.CONTAINER_PROJECT_DIR

    check = container_exec(
        container_name,
        ["test", "-d", f"{project_dir}/.git"],
        user=constants.CONTAINER_USER,
        check=False,
    )
    if check.returncode != 0:
        return GitSummary(available=False)

    status = container_exec(
        container_name,
        ["git", "-C", project_dir, "status", "--short"],
        user=constants.CONTAINER_USER,
        check=False,
    )
    status_text = status.stdout.strip() if status.returncode == 0 else ""

    log = container_exec(
        container_name,
        ["git", "-C", project_dir, "log", "-1", "--oneline"],
        user=constants.CONTAINER_USER,
        check=False,
    )
    last_commit = (
        log.stdout.strip() if log.returncode == 0 and log.stdout.strip() else None
    )

    modified = 0
    untracked = 0
    for line in status_text.splitlines():
        if line.startswith("??"):
            untracked += 1
        else:
            modified += 1

    return GitSummary(
        available=True,
        short_status=status_text,
        last_commit=last_commit,
        modified_count=modified,
        untracked_count=untracked,
    )


def tail_stream_log(container_name: str, lines: int = 20) -> str:
    """
    Return the last N lines of the inner Claude stream log, if present.
    """
    stream_log = f"{constants.CAGE_MSG_DIR}/claude-stream.log"
    result = container_exec(
        container_name,
        ["tail", "-n", str(lines), stream_log],
        user=constants.CONTAINER_USER,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.rstrip()


# ---------------------------------------------------------------------------
# Suggestion
# ---------------------------------------------------------------------------


def _suggest(report: "DiagnosticReport") -> str:
    """
    Return a short actionable suggestion based on the report.
    """
    if not report.container_exists:
        return "Container does not exist. Environment may have been destroyed."

    if not report.container_running:
        return (
            "Container is stopped. Start it with `tc attach` to inspect further, "
            "or inspect the host clone directly."
        )

    p = report.process
    has_work = report.git.available and (
        report.git.modified_count > 0 or report.git.untracked_count > 0
    )

    if p.state == "zombie":
        salvage_hint = (
            " Work appears exportable via `tc salvage` or `tc export`."
            if has_work
            else ""
        )
        return (
            "Inner Claude exited (zombie process). It never reached normal shutdown."
            + salvage_hint
            + " Run `tc logs <env>` to see the final output."
        )

    if p.state == "absent":
        salvage_hint = (
            " Work appears exportable via `tc salvage` or `tc export`."
            if has_work
            else ""
        )
        return (
            "No inner Claude process found. It has exited."
            + salvage_hint
            + " Run `tc logs <env>` for the final output."
        )

    if p.state == "unknown":
        return (
            "Could not determine inner process state (ps failed). "
            "Check container health with `docker ps`."
        )

    # p.state == "alive"
    last_type = report.outbox.last_type
    if last_type == "task_complete":
        return (
            "Inner Claude is alive and task_complete is in the outbox. "
            "Poll should have exited — possible race or --timeout was too short."
        )
    if last_type == "going_idle":
        return (
            "Inner Claude is alive but signaled going_idle. "
            "Send a task_revision via `tc inbox` or re-launch."
        )
    if last_type == "error":
        return (
            "Inner Claude is alive and reported an error. "
            "Inspect with `tc outbox <env> --all`."
        )
    if report.outbox.count == 0:
        return (
            "Inner Claude is alive but has sent no outbox messages yet. "
            "It may still be starting — give it more time, or check `tc logs <env> -f`."
        )

    return (
        "Inner Claude is alive and still working (last message: "
        f"{last_type or 'unknown'}). Consider increasing --timeout "
        "or watch progress with `tc logs <env> -f`."
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_sweep(env_name: str, container_name: str) -> DiagnosticReport:
    """
    Run all diagnostic checks against the given environment and return a
    structured report. Safe to call even if the container is stopped or absent.
    """
    exists = container_exists(container_name)
    running = container_is_running(container_name) if exists else False

    if not running:
        report = DiagnosticReport(
            env_name=env_name,
            container_name=container_name,
            container_exists=exists,
            container_running=running,
            process=ProcessState(state="unknown"),
            outbox=OutboxSummary(),
            git=GitSummary(),
            stream_tail="",
        )
        report.suggestion = _suggest(report)
        return report

    report = DiagnosticReport(
        env_name=env_name,
        container_name=container_name,
        container_exists=True,
        container_running=True,
        process=check_process(container_name),
        outbox=check_outbox(container_name),
        git=check_git(container_name),
        stream_tail=tail_stream_log(container_name, lines=20),
    )
    report.suggestion = _suggest(report)
    return report


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def format_report(report: DiagnosticReport) -> list[str]:
    """
    Return a list of Rich-formatted lines describing the report.
    """
    lines: list[str] = []
    lines.append(f"[bold]Diagnostic report for[/bold] {report.env_name}")
    lines.append(f"[dim]  container:[/dim] {report.container_name}")

    if not report.container_exists:
        lines.append("  [bold red]container does not exist[/bold red]")
    elif not report.container_running:
        lines.append("  [bold yellow]container stopped[/bold yellow]")
    else:
        lines.append("  [green]container running[/green]")

    p = report.process
    if p.state == "alive":
        lines.append(f"  [dim]process:[/dim] [green]alive[/green] (pid={p.pid})")
    elif p.state == "zombie":
        lines.append(f"  [dim]process:[/dim] [bold red]zombie[/bold red] (pid={p.pid})")
    elif p.state == "absent":
        lines.append("  [dim]process:[/dim] [yellow]absent[/yellow]")
    else:
        lines.append("  [dim]process:[/dim] [dim]unknown[/dim]")

    ob = report.outbox
    if ob.count == 0:
        lines.append("  [dim]outbox:[/dim] no messages")
    else:
        ts = ob.last_timestamp or "?"
        lines.append(
            f"  [dim]outbox:[/dim] {ob.count} message(s), last={ob.last_type} @ {ts}"
        )

    g = report.git
    if not g.available:
        lines.append("  [dim]git:[/dim] not a git repo (or container stopped)")
    else:
        parts = []
        if g.modified_count:
            parts.append(f"{g.modified_count} modified")
        if g.untracked_count:
            parts.append(f"{g.untracked_count} untracked")
        status_desc = ", ".join(parts) if parts else "clean"
        commit = g.last_commit or "no commits"
        lines.append(f"  [dim]git:[/dim] {status_desc} | last: {commit}")

    if report.stream_tail:
        tail_preview = report.stream_tail.splitlines()[-3:]
        lines.append("  [dim]stream tail (last 3 lines):[/dim]")
        for t in tail_preview:
            lines.append(f"    [dim]{t[:200]}[/dim]")

    if report.suggestion:
        lines.append(f"[bold cyan]→[/bold cyan] {report.suggestion}")

    return lines
