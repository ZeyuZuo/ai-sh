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


def _config(tmp_path):
    from ai_sh.config import ApiConfig, BehaviorConfig, Config, SafetyConfig

    return Config(
        api=ApiConfig(api_key="test-key"),
        behavior=BehaviorConfig(
            default_confirm="n", history_limit=10, context_commands=2
        ),
        safety=SafetyConfig(hard_block_enabled=True),
        path=tmp_path / "config.toml",
    )
