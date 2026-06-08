import os
import stat

from ai_sh.history import Conversation, HistoryStore, new_history_entry


def test_history_store_appends_and_limits_with_600_permissions(tmp_path) -> None:
    path = tmp_path / "history.json"
    store = HistoryStore(path, limit=2)

    store.append(new_history_entry("one", "echo one", executed=False))
    store.append(new_history_entry("two", "echo two", executed=True, exit_code=0))
    store.append(new_history_entry("three", "echo three", executed=False))

    entries = store.load_entries()
    assert [entry.user_input for entry in entries] == ["two", "three"]
    assert store.recent_commands(5) == ["echo two", "echo three"]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_history_store_tolerates_corruption(tmp_path) -> None:
    path = tmp_path / "history.json"
    path.write_text("{bad json", encoding="utf-8")

    assert HistoryStore(path).load_entries() == []


def test_conversation_trims_messages() -> None:
    conversation = Conversation(max_messages=2)

    conversation.add_user("a")
    conversation.add_assistant("b")
    conversation.add_user("c")

    assert [message["content"] for message in conversation.messages] == ["b", "c"]
