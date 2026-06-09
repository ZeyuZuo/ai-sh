from click.testing import CliRunner

from ai_sh.cli import _run_once, ai, ai_sh
from ai_sh.executor import ExecutionResult
from ai_sh.history import Conversation, HistoryStore
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
    assert "dry-run：已生成并检查命令，没有执行。" in result.output


def test_ai_sh_config_writes_settings(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    monkeypatch.setattr("ai_sh.cli.write_config", _write_config_to(config_path))
    monkeypatch.setattr("ai_sh.cli.load_config", lambda: _config(tmp_path))

    result = CliRunner().invoke(
        ai_sh,
        [
            "config",
            "--base-url",
            "https://api.example.test/v1",
            "--model",
            "example-model",
            "--api-key",
            "secret-key",
        ],
    )

    assert result.exit_code == 0
    assert "配置已保存" in result.output


def test_ai_sh_config_show_redacts_api_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("ai_sh.cli.load_config", lambda: _config(tmp_path))

    result = CliRunner().invoke(ai_sh, ["config", "--show"])

    assert result.exit_code == 0
    assert "api_key: configured" in result.output
    assert "test-key" not in result.output


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

    result = CliRunner().invoke(ai, ["large", "files"])

    assert result.exit_code == 0
    assert "safe：自动执行只读或低风险命令。" in result.output
    assert "命令已成功执行" in result.output
    assert "已执行命令" in result.output
    assert "没有输出" in result.output


def test_ai_can_switch_to_alternative_command(monkeypatch, tmp_path) -> None:
    history_path = tmp_path / "history.json"
    executed: dict[str, str] = {}
    monkeypatch.setattr("ai_sh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "ai_sh.cli.collect_context", lambda recent_commands=None: {"cwd": str(tmp_path)}
    )
    monkeypatch.setattr(
        "ai_sh.cli.generate_command",
        lambda config, messages: CommandResult(
            command="find . -type f -size +100M",
            explanation="finds large files",
            risk_level="caution",
            risk_reason="用户需要选择备选命令。",
            alternatives=["du -sh * | sort -rh", "printf alt"],
        ),
    )
    monkeypatch.setattr(
        "ai_sh.cli.HistoryStore",
        lambda limit: __import__("ai_sh.history").history.HistoryStore(
            history_path, limit=limit
        ),
    )

    def fake_execute(command: str) -> ExecutionResult:
        executed["command"] = command
        return ExecutionResult(command=command, exit_code=0, stdout="alt", stderr="")

    monkeypatch.setattr("ai_sh.cli.execute_command", fake_execute)
    choices = iter([2, "y"])
    monkeypatch.setattr(
        "ai_sh.cli.prompt_confirm",
        lambda default, caution=False, alternatives_count=0: next(choices),
    )

    result = CliRunner().invoke(ai, ["large", "files"])

    assert result.exit_code == 0
    assert executed["command"] == "printf alt"
    assert "已切换到备选命令 2" in result.output


def test_ai_confirms_caution_once(monkeypatch, tmp_path) -> None:
    history_path = tmp_path / "history.json"
    executed: dict[str, str] = {}
    monkeypatch.setattr("ai_sh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "ai_sh.cli.collect_context", lambda recent_commands=None: {"cwd": str(tmp_path)}
    )
    monkeypatch.setattr(
        "ai_sh.cli.generate_command",
        lambda config, messages: CommandResult(
            command="rm -rf ./build",
            explanation="removes build directory",
            risk_level="caution",
            risk_reason="会删除文件。",
        ),
    )
    monkeypatch.setattr(
        "ai_sh.cli.HistoryStore",
        lambda limit: __import__("ai_sh.history").history.HistoryStore(
            history_path, limit=limit
        ),
    )
    monkeypatch.setattr("ai_sh.cli.prompt_confirm", lambda *args, **kwargs: "y")

    def fake_execute(command: str) -> ExecutionResult:
        executed["command"] = command
        return ExecutionResult(command=command, exit_code=0, stdout="", stderr="")

    monkeypatch.setattr("ai_sh.cli.execute_command", fake_execute)

    result = CliRunner().invoke(ai, ["remove", "build"])

    assert result.exit_code == 0
    assert executed["command"] == "rm -rf ./build"
    assert "注意：会删除文件。" in result.output


def test_repl_run_keeps_conversation_and_execution_summary(
    monkeypatch, tmp_path
) -> None:
    history = HistoryStore(tmp_path / "history.json", limit=10)
    conversation = Conversation(max_messages=20)
    config = _config(tmp_path, default_confirm="y")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "ai_sh.cli.collect_context",
        lambda recent_commands=None: {"cwd": str(tmp_path), "recent": recent_commands},
    )

    def fake_build_messages(
        user_input,
        env_context,
        *,
        stdin_context="",
        conversation=None,
        language="zh",
    ):
        captured["conversation_before"] = list(conversation or [])
        captured["env_context"] = env_context
        return [{"role": "user", "content": user_input}]

    monkeypatch.setattr("ai_sh.cli.build_messages", fake_build_messages)
    monkeypatch.setattr(
        "ai_sh.cli.generate_command",
        lambda config, messages: CommandResult(
            command="printf done",
            explanation="prints done",
            risk_level="safe",
        ),
    )
    monkeypatch.setattr(
        "ai_sh.cli.execute_command",
        lambda command: ExecutionResult(
            command=command, exit_code=0, stdout="done", stderr=""
        ),
    )
    monkeypatch.setattr(
        "ai_sh.cli.prompt_confirm",
        lambda default, caution=False, alternatives_count=0: "y",
    )

    _run_once(
        "打印 done",
        stdin_context="",
        dry_run=False,
        config=config,
        history=history,
        conversation=conversation,
    )

    assert captured["conversation_before"] == []
    assert "done" in conversation.messages[-1]["content"]
    assert history.load_entries()[-1].executed is True

    _run_once(
        "把刚才的结果再输出一次",
        stdin_context="",
        dry_run=True,
        config=config,
        history=history,
        conversation=conversation,
    )

    assert captured["conversation_before"]
    assert captured["env_context"]["recent"] == ["printf done"]


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


def _write_config_to(config_path):
    from ai_sh.config import write_config as real_write_config

    def write_to_temp(**kwargs):
        kwargs["path"] = config_path
        return real_write_config(**kwargs)

    return write_to_temp
