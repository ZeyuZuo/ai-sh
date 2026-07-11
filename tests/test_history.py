import os
import stat

from tmksh.history import HistoryStore, new_history_entry


def test_history_store_appends_and_limits_with_600_permissions(tmp_path) -> None:
    path = tmp_path / "history.json"
    store = HistoryStore(path, limit=2)

    store.append(new_history_entry("one", "echo one"))
    store.append(new_history_entry("two", "echo two"))
    store.append(new_history_entry("three", "echo three"))

    entries = store.load_entries()
    assert [entry.user_input for entry in entries] == ["two", "three"]
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_history_store_tolerates_corruption(tmp_path) -> None:
    path = tmp_path / "history.json"
    path.write_text("{bad json", encoding="utf-8")

    assert HistoryStore(path).load_entries() == []
