"""Persistent command history and REPL conversation history."""

from __future__ import annotations

import json
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from tmksh.config import CONFIG_DIR
HISTORY_PATH = CONFIG_DIR / "history.json"


@dataclass(frozen=True)
class HistoryEntry:
    """A persisted command-generation history entry."""

    timestamp: str
    user_input: str
    command: str


class HistoryStore:
    """Read and write local tmksh history."""

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
            if (
                isinstance(timestamp, str)
                and isinstance(user_input, str)
                and isinstance(command, str)
            ):
                entries.append(HistoryEntry(timestamp, user_input, command))
        return entries[-self.limit :]

    def append(self, entry: HistoryEntry) -> None:
        """Append an entry and persist the bounded history file."""

        entries = self.load_entries()
        entries.append(entry)
        self._write(entries[-self.limit :])

    def _write(self, entries: list[HistoryEntry]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = json.dumps(
            [asdict(entry) for entry in entries],
            ensure_ascii=False,
            indent=2,
        )
        self.path.write_text(payload, encoding="utf-8")
        self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def new_history_entry(user_input: str, command: str) -> HistoryEntry:
    """Create a timestamped history entry."""

    return HistoryEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        user_input=user_input,
        command=command,
    )
