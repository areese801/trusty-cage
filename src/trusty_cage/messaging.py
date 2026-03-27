"""
File-based message bus for inner/outer Claude communication.

Messages are JSON files in well-known directories inside the container:
  - outbox: inner Claude writes, outer Claude reads (via docker exec)
  - inbox: outer Claude writes, inner Claude reads (local files)

Kafka-like semantics: timestamped messages, cursor-based consumption, ACK.
"""

import json
import logging
import secrets
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trusty_cage import constants
from trusty_cage.docker import container_exec, copy_to_container

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

MESSAGE_TYPES = frozenset(
    {
        "task_complete",
        "info_request",
        "progress_update",
        "error",
        "info_response",
        "ack",
    }
)


@dataclass
class Message:
    """
    Envelope for a single message in the inbox/outbox.
    """

    id: str
    type: str
    timestamp: str
    payload: dict[str, Any]
    version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to a plain dict for JSON encoding.
        """
        return asdict(self)

    def to_json(self) -> str:
        """
        Serialize to a JSON string.
        """
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        """
        Deserialize from a dict. Raises KeyError/TypeError on missing fields.
        """
        return cls(
            id=data["id"],
            type=data["type"],
            timestamp=data["timestamp"],
            payload=data["payload"],
            version=data.get("version", SCHEMA_VERSION),
        )

    @classmethod
    def from_json(cls, raw: str) -> "Message | None":
        """
        Parse a JSON string into a Message. Returns None if malformed.
        """
        try:
            data = json.loads(raw)
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Skipping malformed message: %s", e)
            return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_id() -> str:
    """
    Generate a unique message ID.
    Format: msg-<compact_timestamp>-<4_hex_random>
    """
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S%f")[:19]
    rand = secrets.token_hex(2)
    return f"msg-{ts}-{rand}"


def _generate_timestamp() -> str:
    """
    Generate an ISO-8601 UTC timestamp with millisecond precision.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _timestamp_to_filename(iso_ts: str) -> str:
    """
    Convert an ISO timestamp to a filesystem-safe filename (no extension).
    Replaces colons with dashes so lexicographic sort = chronological order.
    """
    return iso_ts.replace(":", "-")


def _filename_to_timestamp(filename: str) -> str:
    """
    Convert a filename (without .json) back to an ISO timestamp.
    Reverses _timestamp_to_filename by restoring colons at known positions.
    """
    stem = filename.removesuffix(".json")
    # ISO format: YYYY-MM-DDTHH:MM:SS.mmmZ
    # Filename:   YYYY-MM-DDTHH-MM-SS.mmmZ
    # Positions 13 and 16 should be colons
    chars = list(stem)
    if len(chars) >= 17:
        chars[13] = ":"
        chars[16] = ":"
    return "".join(chars)


def _build_message(msg_type: str, payload: dict[str, Any]) -> Message:
    """
    Build a new Message with generated id and timestamp.
    """
    return Message(
        id=_generate_id(),
        type=msg_type,
        timestamp=_generate_timestamp(),
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------


def init_messaging_dirs(container_name: str) -> None:
    """
    Create the .cage/{outbox,inbox,cursor} directory tree inside the container.
    Called during `trusty-cage create`.
    """
    container_exec(
        container_name,
        [
            "mkdir",
            "-p",
            constants.CAGE_OUTBOX_DIR,
            constants.CAGE_INBOX_DIR,
            constants.CAGE_CURSOR_DIR,
        ],
        user=constants.CONTAINER_USER,
    )


# ---------------------------------------------------------------------------
# Cursor management
# ---------------------------------------------------------------------------


def get_cursor(container_name: str) -> str | None:
    """
    Read the outbox cursor (last-read timestamp) from the container.
    Returns None if no cursor has been set.
    """
    result = container_exec(
        container_name,
        ["cat", constants.CAGE_OUTBOX_CURSOR],
        user=constants.CONTAINER_USER,
        check=False,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value if value else None


def set_cursor(container_name: str, timestamp: str) -> None:
    """
    Write the outbox cursor to the container.
    """
    container_exec(
        container_name,
        ["bash", "-c", f"cat > {constants.CAGE_OUTBOX_CURSOR}"],
        user=constants.CONTAINER_USER,
        input=timestamp,
    )


# ---------------------------------------------------------------------------
# Read from outbox (outer reads inner's messages)
# ---------------------------------------------------------------------------


def _list_outbox_files(container_name: str) -> list[str]:
    """
    List .json files in the outbox, sorted lexicographically (chronological).
    """
    result = container_exec(
        container_name,
        ["ls", "-1", constants.CAGE_OUTBOX_DIR],
        user=constants.CONTAINER_USER,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    files = [f for f in result.stdout.strip().split("\n") if f.endswith(".json")]
    files.sort()
    return files


def _read_container_file(container_name: str, path: str) -> str | None:
    """
    Read a file inside the container. Returns None on failure.
    """
    result = container_exec(
        container_name,
        ["cat", path],
        user=constants.CONTAINER_USER,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def read_outbox(container_name: str, since_cursor: bool = True) -> list[Message]:
    """
    Read messages from the container's outbox.

    If since_cursor is True, only returns messages newer than the stored cursor.
    Silently skips malformed JSON files.
    """
    files = _list_outbox_files(container_name)
    if not files:
        return []

    if since_cursor:
        cursor = get_cursor(container_name)
        if cursor:
            cursor_filename = _timestamp_to_filename(cursor) + ".json"
            files = [f for f in files if f > cursor_filename]

    messages = []
    for filename in files:
        raw = _read_container_file(
            container_name, f"{constants.CAGE_OUTBOX_DIR}/{filename}"
        )
        if raw is None:
            continue
        msg = Message.from_json(raw)
        if msg is not None:
            messages.append(msg)

    return messages


# ---------------------------------------------------------------------------
# Write to inbox (outer writes to inner's inbox)
# ---------------------------------------------------------------------------


def send_to_inbox(
    container_name: str, msg_type: str, payload: dict[str, Any]
) -> Message:
    """
    Create a message and write it to the container's inbox.
    Returns the Message that was written.
    """
    msg = _build_message(msg_type, payload)
    filename = _timestamp_to_filename(msg.timestamp) + ".json"
    content = msg.to_json()

    # For large payloads, use docker cp via temp file
    if len(content) > 4096:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            copy_to_container(
                tmp_path,
                container_name,
                f"{constants.CAGE_INBOX_DIR}/{filename}",
            )
            container_exec(
                container_name,
                [
                    "chown",
                    f"{constants.CONTAINER_USER}:{constants.CONTAINER_USER}",
                    f"{constants.CAGE_INBOX_DIR}/{filename}",
                ],
                user="root",
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    else:
        container_exec(
            container_name,
            ["bash", "-c", f"cat > {constants.CAGE_INBOX_DIR}/{filename}"],
            user=constants.CONTAINER_USER,
            input=content,
        )

    return msg


def send_ack(container_name: str, acked_id: str) -> Message:
    """
    Send an ACK message to the inbox for a given message ID.
    """
    return send_to_inbox(container_name, "ack", {"acked_id": acked_id})


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


def has_task_complete(container_name: str) -> bool:
    """
    Check if there's a task_complete message in the outbox (unread since cursor).
    """
    messages = read_outbox(container_name, since_cursor=True)
    return any(m.type == "task_complete" for m in messages)


def get_latest_by_type(container_name: str, msg_type: str) -> "Message | None":
    """
    Get the most recent message of a given type from the outbox.
    Reads all messages (ignores cursor) and returns the last match.
    """
    messages = read_outbox(container_name, since_cursor=False)
    matches = [m for m in messages if m.type == msg_type]
    return matches[-1] if matches else None
