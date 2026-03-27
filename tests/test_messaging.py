"""
Tests for messaging module.
"""

import json
import subprocess

import pytest

from trusty_cage import constants
from trusty_cage.messaging import (
    Message,
    _build_message,
    _filename_to_timestamp,
    _generate_id,
    _generate_timestamp,
    _timestamp_to_filename,
    get_cursor,
    get_latest_by_type,
    has_task_complete,
    init_messaging_dirs,
    read_outbox,
    send_ack,
    send_to_inbox,
    set_cursor,
)


class TestMessage:
    def test_to_dict_roundtrip(self):
        msg = Message(
            id="msg-test-0001",
            type="task_complete",
            timestamp="2026-03-26T14:30:00.000Z",
            payload={"summary": "did stuff", "exit_code": 0},
        )
        d = msg.to_dict()
        assert d["id"] == "msg-test-0001"
        assert d["type"] == "task_complete"
        assert d["payload"]["summary"] == "did stuff"

    def test_to_json_and_from_json(self):
        msg = Message(
            id="msg-test-0001",
            type="progress_update",
            timestamp="2026-03-26T14:30:00.000Z",
            payload={"status": "working"},
        )
        raw = msg.to_json()
        restored = Message.from_json(raw)
        assert restored is not None
        assert restored.id == msg.id
        assert restored.type == msg.type
        assert restored.payload == msg.payload

    def test_from_json_malformed(self):
        assert Message.from_json("not json") is None

    def test_from_json_missing_fields(self):
        assert Message.from_json('{"id": "x"}') is None

    def test_from_dict_missing_key(self):
        with pytest.raises(KeyError):
            Message.from_dict({"id": "x"})

    def test_version_defaults(self):
        msg = Message(id="x", type="ack", timestamp="t", payload={})
        assert msg.version == 1

    def test_from_dict_preserves_version(self):
        data = {
            "id": "x",
            "type": "ack",
            "timestamp": "t",
            "payload": {},
            "version": 2,
        }
        msg = Message.from_dict(data)
        assert msg.version == 2


class TestHelpers:
    def test_generate_id_format(self):
        msg_id = _generate_id()
        assert msg_id.startswith("msg-")
        parts = msg_id.split("-")
        assert len(parts) == 3

    def test_generate_timestamp_format(self):
        ts = _generate_timestamp()
        assert ts.endswith("Z")
        assert "T" in ts

    def test_timestamp_filename_roundtrip(self):
        ts = "2026-03-26T14:30:00.000Z"
        filename = _timestamp_to_filename(ts)
        assert ":" not in filename
        restored = _filename_to_timestamp(filename + ".json")
        assert restored == ts

    def test_build_message(self):
        msg = _build_message("error", {"message": "oops"})
        assert msg.type == "error"
        assert msg.payload["message"] == "oops"
        assert msg.id.startswith("msg-")


class TestInitMessagingDirs:
    def test_calls_mkdir(self, mocker):
        mock_exec = mocker.patch("trusty_cage.messaging.container_exec")
        init_messaging_dirs("my-container")
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args
        assert "mkdir" in call_args[0][1]
        assert constants.CAGE_OUTBOX_DIR in call_args[0][1]
        assert constants.CAGE_INBOX_DIR in call_args[0][1]
        assert constants.CAGE_CURSOR_DIR in call_args[0][1]


class TestCursor:
    def test_get_cursor_returns_none_when_missing(self, mocker):
        mocker.patch(
            "trusty_cage.messaging.container_exec",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=""
            ),
        )
        assert get_cursor("c") is None

    def test_get_cursor_returns_value(self, mocker):
        mocker.patch(
            "trusty_cage.messaging.container_exec",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="2026-03-26T14:30:00.000Z\n", stderr=""
            ),
        )
        assert get_cursor("c") == "2026-03-26T14:30:00.000Z"

    def test_set_cursor(self, mocker):
        mock_exec = mocker.patch("trusty_cage.messaging.container_exec")
        set_cursor("c", "2026-03-26T14:30:00.000Z")
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args
        assert call_args[1]["input"] == "2026-03-26T14:30:00.000Z"


class TestReadOutbox:
    def _mock_exec(self, mocker, ls_output, file_contents, cursor=None):
        """
        Helper to mock container_exec for read_outbox tests.
        ls_output: string from ls -1
        file_contents: dict of {filename: json_string}
        cursor: cursor value or None
        """

        def side_effect(container, command, **kwargs):
            cmd_str = " ".join(command)
            if "ls" in cmd_str:
                return subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=ls_output, stderr=""
                )
            if constants.CAGE_OUTBOX_CURSOR in cmd_str:
                if cursor:
                    return subprocess.CompletedProcess(
                        args=[], returncode=0, stdout=cursor, stderr=""
                    )
                return subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="", stderr=""
                )
            # cat a specific file
            for fname, content in file_contents.items():
                if fname in cmd_str:
                    return subprocess.CompletedProcess(
                        args=[], returncode=0, stdout=content, stderr=""
                    )
            return subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=""
            )

        return mocker.patch(
            "trusty_cage.messaging.container_exec", side_effect=side_effect
        )

    def test_empty_outbox(self, mocker):
        self._mock_exec(mocker, "", {})
        assert read_outbox("c") == []

    def test_reads_all_messages(self, mocker):
        msg1 = Message(
            id="msg-1",
            type="progress_update",
            timestamp="2026-03-26T14:00:00.000Z",
            payload={"status": "starting"},
        )
        msg2 = Message(
            id="msg-2",
            type="task_complete",
            timestamp="2026-03-26T14:30:00.000Z",
            payload={"summary": "done", "exit_code": 0},
        )
        files = {
            "2026-03-26T14-00-00.000Z.json": msg1.to_json(),
            "2026-03-26T14-30-00.000Z.json": msg2.to_json(),
        }
        ls = "\n".join(sorted(files.keys()))
        self._mock_exec(mocker, ls, files)

        messages = read_outbox("c", since_cursor=False)
        assert len(messages) == 2
        assert messages[0].type == "progress_update"
        assert messages[1].type == "task_complete"

    def test_respects_cursor(self, mocker):
        msg1 = Message(
            id="msg-1",
            type="progress_update",
            timestamp="2026-03-26T14:00:00.000Z",
            payload={"status": "starting"},
        )
        msg2 = Message(
            id="msg-2",
            type="task_complete",
            timestamp="2026-03-26T14:30:00.000Z",
            payload={"summary": "done", "exit_code": 0},
        )
        files = {
            "2026-03-26T14-00-00.000Z.json": msg1.to_json(),
            "2026-03-26T14-30-00.000Z.json": msg2.to_json(),
        }
        ls = "\n".join(sorted(files.keys()))
        self._mock_exec(mocker, ls, files, cursor="2026-03-26T14:00:00.000Z")

        messages = read_outbox("c", since_cursor=True)
        assert len(messages) == 1
        assert messages[0].type == "task_complete"

    def test_skips_malformed_json(self, mocker):
        files = {
            "2026-03-26T14-00-00.000Z.json": "not valid json",
            "2026-03-26T14-30-00.000Z.json": Message(
                id="msg-2",
                type="task_complete",
                timestamp="2026-03-26T14:30:00.000Z",
                payload={"summary": "done", "exit_code": 0},
            ).to_json(),
        }
        ls = "\n".join(sorted(files.keys()))
        self._mock_exec(mocker, ls, files)

        messages = read_outbox("c", since_cursor=False)
        assert len(messages) == 1
        assert messages[0].id == "msg-2"


class TestSendToInbox:
    def test_sends_small_message(self, mocker):
        mock_exec = mocker.patch("trusty_cage.messaging.container_exec")
        msg = send_to_inbox("c", "info_response", {"request_id": "r1", "content": "hi"})

        assert msg.type == "info_response"
        assert msg.payload["request_id"] == "r1"

        # Should have used container_exec with input (not docker cp)
        call_args = mock_exec.call_args
        assert call_args[1]["input"] is not None
        written_json = json.loads(call_args[1]["input"])
        assert written_json["type"] == "info_response"

    def test_sends_large_message_via_docker_cp(self, mocker):
        mocker.patch("trusty_cage.messaging.container_exec")
        mock_cp = mocker.patch("trusty_cage.messaging.copy_to_container")

        large_content = "x" * 5000
        msg = send_to_inbox(
            "c", "info_response", {"request_id": "r1", "content": large_content}
        )

        assert msg.type == "info_response"
        mock_cp.assert_called_once()


class TestSendAck:
    def test_sends_ack(self, mocker):
        mocker.patch("trusty_cage.messaging.container_exec")
        msg = send_ack("c", "msg-original-123")

        assert msg.type == "ack"
        assert msg.payload["acked_id"] == "msg-original-123"


class TestConvenience:
    def test_has_task_complete_true(self, mocker):
        msg = Message(
            id="msg-1",
            type="task_complete",
            timestamp="2026-03-26T14:30:00.000Z",
            payload={"summary": "done", "exit_code": 0},
        )
        mocker.patch("trusty_cage.messaging.read_outbox", return_value=[msg])
        assert has_task_complete("c") is True

    def test_has_task_complete_false(self, mocker):
        msg = Message(
            id="msg-1",
            type="progress_update",
            timestamp="2026-03-26T14:30:00.000Z",
            payload={"status": "working"},
        )
        mocker.patch("trusty_cage.messaging.read_outbox", return_value=[msg])
        assert has_task_complete("c") is False

    def test_get_latest_by_type(self, mocker):
        msg1 = Message(
            id="msg-1",
            type="progress_update",
            timestamp="2026-03-26T14:00:00.000Z",
            payload={"status": "starting"},
        )
        msg2 = Message(
            id="msg-2",
            type="progress_update",
            timestamp="2026-03-26T14:30:00.000Z",
            payload={"status": "finishing"},
        )
        mocker.patch("trusty_cage.messaging.read_outbox", return_value=[msg1, msg2])
        result = get_latest_by_type("c", "progress_update")
        assert result is not None
        assert result.id == "msg-2"

    def test_get_latest_by_type_not_found(self, mocker):
        mocker.patch("trusty_cage.messaging.read_outbox", return_value=[])
        assert get_latest_by_type("c", "task_complete") is None
