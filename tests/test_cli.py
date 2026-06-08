from click.testing import CliRunner

from ai_sh.cli import ai
from ai_sh.llm import CommandResult


def test_ai_dry_run_does_not_execute(monkeypatch, tmp_path) -> None:
    history_path = tmp_path / "history.json"

    monkeypatch.setattr("ai_sh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "ai_sh.cli.collect_context", lambda recent_commands=None: {"cwd": str(tmp_path)}
    )
    monkeypatch.setattr(
        "ai_sh.cli.generate_command",
        lambda config, messages: CommandResult(
            command="printf should-not-run",
            explanation="prints text",
            risk_level="safe",
        ),
    )
    monkeypatch.setattr(
        "ai_sh.cli.HistoryStore",
        lambda limit: __import__("ai_sh.history").history.HistoryStore(
            history_path, limit=limit
        ),
    )

    called = False

    def fake_execute(command: str):
        nonlocal called
        called = True

    monkeypatch.setattr("ai_sh.cli.execute_command", fake_execute)

    result = CliRunner().invoke(ai, ["--dry-run", "say", "hello"])

    assert result.exit_code == 0
    assert called is False
    assert "dry-run" in result.output


def test_single_run_does_not_inject_persisted_history(monkeypatch, tmp_path) -> None:
    history_module = __import__("ai_sh.history").history
    history_path = tmp_path / "history.json"
    store = history_module.HistoryStore(history_path, limit=10)
    store.append(history_module.new_history_entry("old", "echo old", executed=False))
    captured: dict[str, object] = {}

    monkeypatch.setattr("ai_sh.cli.load_config", lambda: _config(tmp_path))

    def fake_collect_context(recent_commands=None):
        captured["recent_commands"] = recent_commands
        return {"cwd": str(tmp_path), "recent_commands": recent_commands}

    monkeypatch.setattr("ai_sh.cli.collect_context", fake_collect_context)
    monkeypatch.setattr(
        "ai_sh.cli.generate_command",
        lambda config, messages: CommandResult(
            command="printf ok",
            explanation="prints text",
            risk_level="safe",
        ),
    )
    monkeypatch.setattr(
        "ai_sh.cli.HistoryStore",
        lambda limit: history_module.HistoryStore(history_path, limit=limit),
    )

    result = CliRunner().invoke(ai, ["--dry-run", "say", "hello"])

    assert result.exit_code == 0
    assert captured["recent_commands"] == []


def test_ai_blocks_dangerous_command(monkeypatch, tmp_path) -> None:
    history_path = tmp_path / "history.json"
    monkeypatch.setattr("ai_sh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "ai_sh.cli.collect_context", lambda recent_commands=None: {"cwd": str(tmp_path)}
    )
    monkeypatch.setattr(
        "ai_sh.cli.generate_command",
        lambda config, messages: CommandResult(
            command="rm -rf /",
            explanation="danger",
            risk_level="danger",
            risk_reason="will delete system",
        ),
    )
    monkeypatch.setattr(
        "ai_sh.cli.HistoryStore",
        lambda limit: __import__("ai_sh.history").history.HistoryStore(
            history_path, limit=limit
        ),
    )

    result = CliRunner().invoke(ai, ["delete", "everything"])

    assert result.exit_code == 0
    assert "已拦截危险命令" in result.output


def test_ai_executes_safe_command_and_explains_empty_output(
    monkeypatch, tmp_path
) -> None:
    from ai_sh.executor import ExecutionResult

    history_path = tmp_path / "history.json"
    monkeypatch.setattr(
        "ai_sh.cli.load_config", lambda: _config(tmp_path, default_confirm="y")
    )
    monkeypatch.setattr(
        "ai_sh.cli.collect_context", lambda recent_commands=None: {"cwd": str(tmp_path)}
    )
    monkeypatch.setattr(
        "ai_sh.cli.generate_command",
        lambda config, messages: CommandResult(
            command="find . -type f -size +100M",
            explanation="finds large files",
            risk_level="safe",
        ),
    )
    monkeypatch.setattr(
        "ai_sh.cli.HistoryStore",
        lambda limit: __import__("ai_sh.history").history.HistoryStore(
            history_path, limit=limit
        ),
    )
    monkeypatch.setattr(
        "ai_sh.cli.execute_command",
        lambda command: ExecutionResult(
            command=command, exit_code=0, stdout="", stderr=""
        ),
    )

    result = CliRunner().invoke(ai, ["large", "files"], input="y\n")

    assert result.exit_code == 0
    assert "命令已成功执行" in result.output
    assert "没有输出" in result.output


def _config(tmp_path, default_confirm="n"):
    from ai_sh.config import ApiConfig, BehaviorConfig, Config, SafetyConfig

    return Config(
        api=ApiConfig(api_key="test-key"),
        behavior=BehaviorConfig(
            default_confirm=default_confirm, history_limit=10, context_commands=2
        ),
        safety=SafetyConfig(hard_block_enabled=True),
        path=tmp_path / "config.toml",
    )
