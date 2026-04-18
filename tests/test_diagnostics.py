"""
Tests for the diagnostics module.
"""

import subprocess


from trusty_cage.diagnostics import (
    DiagnosticReport,
    GitSummary,
    OutboxSummary,
    ProcessState,
    _suggest,
    check_git,
    check_outbox,
    check_process,
    format_report,
    run_sweep,
)

DIAG = "trusty_cage.diagnostics"


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    """
    Helper to build a CompletedProcess-like object for mocks.
    """
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestCheckProcess:
    def test_alive_process_reported(self, mocker):
        ps_output = (
            " 1234 Sl   /usr/bin/node /usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js\n"
            " 9999 S    bash\n"
        )
        mocker.patch(
            f"{DIAG}.container_exec", return_value=_completed(stdout=ps_output)
        )

        state = check_process("c")
        assert state.state == "alive"
        assert state.pid == 1234

    def test_zombie_process_reported(self, mocker):
        # A defunct node+claude-code process (parent never reaped it)
        ps_output = (
            " 2222 Z    node /usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js <defunct>\n"
            " 5555 S    bash\n"
        )
        mocker.patch(
            f"{DIAG}.container_exec", return_value=_completed(stdout=ps_output)
        )

        state = check_process("c")
        assert state.state == "zombie"
        assert state.pid == 2222

    def test_absent_process_reported(self, mocker):
        ps_output = " 5555 S    bash\n 7777 S    sshd\n"
        mocker.patch(
            f"{DIAG}.container_exec", return_value=_completed(stdout=ps_output)
        )

        state = check_process("c")
        assert state.state == "absent"
        assert state.pid is None

    def test_ignores_cage_helpers_and_grep(self, mocker):
        """
        cage-send / cage-wait / grep matching 'claude' must not count as the inner.
        """
        ps_output = (
            " 100 S    cage-send progress_update\n"
            " 200 S    grep claude\n"
            " 300 S    bash -c 'ps | grep claude'\n"
        )
        mocker.patch(
            f"{DIAG}.container_exec", return_value=_completed(stdout=ps_output)
        )

        state = check_process("c")
        assert state.state == "absent"

    def test_ignores_tail_of_claude_stream_log(self, mocker):
        """
        Real-world false positive: the inner claude may spawn `tail -f claude-stream.log`
        as a background task. The stream log path contains 'claude' but tail is not the
        inner claude process.
        """
        ps_output = (
            " 909 S    tail -f -n 50 /home/trustycage/.cage/claude-stream.log\n"
            " 5555 S    bash\n"
        )
        mocker.patch(
            f"{DIAG}.container_exec", return_value=_completed(stdout=ps_output)
        )

        state = check_process("c")
        assert state.state == "absent"

    def test_unknown_when_ps_fails(self, mocker):
        mocker.patch(
            f"{DIAG}.container_exec",
            return_value=_completed(returncode=1, stderr="exec failed"),
        )
        state = check_process("c")
        assert state.state == "unknown"


class TestCheckOutbox:
    def test_empty_outbox(self, mocker):
        mocker.patch(
            f"{DIAG}.container_exec",
            return_value=_completed(stdout="", returncode=0),
        )
        summary = check_outbox("c")
        assert summary.count == 0
        assert summary.last_type is None

    def test_reads_last_message(self, mocker):
        # First call: ls. Second call: cat the last file.
        ls_out = (
            "/home/trustycage/.cage/outbox/2026-04-18T10-00-00.000Z.json\n"
            "/home/trustycage/.cage/outbox/2026-04-18T10-05-00.000Z.json\n"
        )
        cat_out = '{"id":"x","type":"task_complete","timestamp":"2026-04-18T10:05:00.000Z","payload":{"summary":"ok","exit_code":0},"version":1}'
        mocker.patch(
            f"{DIAG}.container_exec",
            side_effect=[_completed(stdout=ls_out), _completed(stdout=cat_out)],
        )

        summary = check_outbox("c")
        assert summary.count == 2
        assert summary.last_type == "task_complete"
        assert summary.last_timestamp == "2026-04-18T10:05:00.000Z"
        assert summary.last_filename == "2026-04-18T10-05-00.000Z.json"

    def test_malformed_last_message_does_not_crash(self, mocker):
        ls_out = "/home/trustycage/.cage/outbox/a.json\n"
        mocker.patch(
            f"{DIAG}.container_exec",
            side_effect=[_completed(stdout=ls_out), _completed(stdout="not json")],
        )
        summary = check_outbox("c")
        assert summary.count == 1
        assert summary.last_type is None


class TestCheckGit:
    def test_unavailable_when_no_git_dir(self, mocker):
        mocker.patch(f"{DIAG}.container_exec", return_value=_completed(returncode=1))
        g = check_git("c")
        assert g.available is False

    def test_counts_modified_and_untracked(self, mocker):
        status_out = " M file1.py\n M file2.py\n?? newfile.py\n"
        log_out = "abc123 initial commit"
        mocker.patch(
            f"{DIAG}.container_exec",
            side_effect=[
                _completed(returncode=0),  # test -d .git
                _completed(stdout=status_out),  # git status --short
                _completed(stdout=log_out),  # git log -1 --oneline
            ],
        )
        g = check_git("c")
        assert g.available is True
        assert g.modified_count == 2
        assert g.untracked_count == 1
        assert g.last_commit == "abc123 initial commit"


class TestSuggest:
    def _report(self, **overrides):
        defaults = dict(
            env_name="e",
            container_name="c",
            container_exists=True,
            container_running=True,
            process=ProcessState(state="alive", pid=1),
            outbox=OutboxSummary(count=0),
            git=GitSummary(available=True),
            stream_tail="",
        )
        defaults.update(overrides)
        return DiagnosticReport(**defaults)

    def test_zombie_with_work_suggests_salvage(self):
        r = self._report(
            process=ProcessState(state="zombie", pid=1),
            git=GitSummary(available=True, modified_count=3),
        )
        s = _suggest(r)
        assert "zombie" in s.lower()
        assert "salvage" in s.lower() or "export" in s.lower()

    def test_absent_with_work_suggests_salvage(self):
        r = self._report(
            process=ProcessState(state="absent"),
            git=GitSummary(available=True, untracked_count=2),
        )
        s = _suggest(r)
        assert "salvage" in s.lower() or "export" in s.lower()

    def test_alive_with_task_complete_flags_race(self):
        r = self._report(
            process=ProcessState(state="alive", pid=5),
            outbox=OutboxSummary(count=1, last_type="task_complete"),
        )
        s = _suggest(r)
        assert "race" in s.lower() or "timeout" in s.lower()

    def test_stopped_container_suggests_start(self):
        r = self._report(container_running=False)
        s = _suggest(r)
        assert "stop" in s.lower() or "start" in s.lower()

    def test_missing_container_reports_destroyed(self):
        r = self._report(container_exists=False, container_running=False)
        s = _suggest(r)
        assert "does not exist" in s.lower() or "destroyed" in s.lower()


class TestRunSweep:
    def test_stopped_container_short_circuits(self, mocker):
        mocker.patch(f"{DIAG}.container_exists", return_value=True)
        mocker.patch(f"{DIAG}.container_is_running", return_value=False)
        # container_exec must NOT be called for a stopped container
        exec_mock = mocker.patch(f"{DIAG}.container_exec")

        report = run_sweep("env-x", "isolated-dev-env-x")
        assert report.container_exists is True
        assert report.container_running is False
        assert report.process.state == "unknown"
        assert exec_mock.call_count == 0

    def test_absent_container(self, mocker):
        mocker.patch(f"{DIAG}.container_exists", return_value=False)
        mocker.patch(f"{DIAG}.container_is_running", return_value=False)
        report = run_sweep("env-x", "isolated-dev-env-x")
        assert report.container_exists is False
        assert "does not exist" in report.suggestion.lower()

    def test_full_sweep_happy_path(self, mocker):
        """
        All checks return healthy values; suggestion is the 'still working' path.
        """
        mocker.patch(f"{DIAG}.container_exists", return_value=True)
        mocker.patch(f"{DIAG}.container_is_running", return_value=True)
        mocker.patch(
            f"{DIAG}.check_process", return_value=ProcessState(state="alive", pid=10)
        )
        mocker.patch(
            f"{DIAG}.check_outbox",
            return_value=OutboxSummary(
                count=2,
                last_type="progress_update",
                last_timestamp="2026-04-18T10:00:00.000Z",
            ),
        )
        mocker.patch(
            f"{DIAG}.check_git",
            return_value=GitSummary(available=True, last_commit="abc"),
        )
        mocker.patch(f"{DIAG}.tail_stream_log", return_value="log line")

        report = run_sweep("e", "c")
        assert report.process.state == "alive"
        assert report.outbox.last_type == "progress_update"
        assert (
            "working" in report.suggestion.lower()
            or "progress" in report.suggestion.lower()
        )


class TestFormatReport:
    def test_format_includes_key_facts(self):
        r = DiagnosticReport(
            env_name="myenv",
            container_name="isolated-dev-myenv",
            container_exists=True,
            container_running=True,
            process=ProcessState(state="zombie", pid=42),
            outbox=OutboxSummary(
                count=3, last_type="progress_update", last_timestamp="t"
            ),
            git=GitSummary(available=True, modified_count=2, last_commit="abc foo"),
            stream_tail="line1\nline2\nline3\n",
            suggestion="Do the thing.",
        )
        lines = format_report(r)
        text = "\n".join(lines)
        assert "myenv" in text
        assert "zombie" in text
        assert "42" in text
        assert "3 message" in text or "3 message(s)" in text
        assert "Do the thing" in text
