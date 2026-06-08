"""Persistent command history and REPL conversation history."""

from __future__ import annotations

import json
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from ai_sh.config import CONFIG_DIR
from ai_sh.llm import ChatMessage

HISTORY_PATH = CONFIG_DIR / "history.json"


@dataclass(frozen=True)
class HistoryEntry:
    """A persisted command-generation history entry."""

    timestamp: str
    user_input: str
    command: str
    executed: bool
    exit_code: int | None = None


class HistoryStore:
    """Read and write local ai-sh history."""

    def __init__(self, path: Path = HISTORY_PATH, *, limit: int = 50) -> None:
        self.path = path
        self.limit = limit

    def load_entries(self) -> list[HistoryEntry]:
        """Load persisted history entries, tolerating corrupt files."""

        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        entries: list[HistoryEntry] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            timestamp = item.get("timestamp")
            user_input = item.get("user_input")
            command = item.get("command")
            executed = item.get("executed")
            exit_code = item.get("exit_code")
            if (
                isinstance(timestamp, str)
                and isinstance(user_input, str)
                and isinstance(command, str)
                and isinstance(executed, bool)
                and (isinstance(exit_code, int) or exit_code is None)
            ):
                entries.append(
                    HistoryEntry(timestamp, user_input, command, executed, exit_code)
                )
        return entries[-self.limit :]

    def append(self, entry: HistoryEntry) -> None:
        """Append an entry and persist the bounded history file."""

        entries = self.load_entries()
        entries.append(entry)
        self._write(entries[-self.limit :])

    def recent_commands(self, count: int) -> list[str]:
        """Return recently generated commands for prompt context."""

        return [
            entry.command for entry in self.load_entries()[-count:] if entry.command
        ]

    def _write(self, entries: list[HistoryEntry]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = json.dumps(
            [asdict(entry) for entry in entries],
            ensure_ascii=False,
            indent=2,
        )
        self.path.write_text(payload, encoding="utf-8")
        self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)


class Conversation:
    """In-memory REPL conversation context."""

    def __init__(self, *, max_messages: int = 20) -> None:
        self.max_messages = max_messages
        self.messages: list[ChatMessage] = []

    def add_user(self, content: str) -> None:
        """Add a user message."""

        self.messages.append({"role": "user", "content": content})
        self._trim()

    def add_assistant(self, content: str) -> None:
        """Add an assistant message."""

        self.messages.append({"role": "assistant", "content": content})
        self._trim()

    def add_execution_summary(self, summary: str) -> None:
        """Add a short execution summary as user-visible context."""

        self.add_user("上一条命令执行结果摘要:\n" + summary[:500])

    def _trim(self) -> None:
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]


def new_history_entry(
    user_input: str,
    command: str,
    *,
    executed: bool,
    exit_code: int | None = None,
) -> HistoryEntry:
    """Create a timestamped history entry."""

    return HistoryEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        user_input=user_input,
        command=command,
        executed=executed,
        exit_code=exit_code,
    )
