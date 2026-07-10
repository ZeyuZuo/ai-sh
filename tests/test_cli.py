import pytest
from click.testing import CliRunner

from ai_sh.cli import _read_stdin_if_piped, _run_legacy_once, ai, ai_sh
from ai_sh.protocol import MAX_STDIN_CONTEXT_CHARS
from ai_sh.executor import ExecutionResult
from ai_sh.history import Conversation, HistoryStore
from ai_sh.llm import AssistantResult
from ai_sh.suggestion import Suggestion


@pytest.mark.parametrize("risk_level", ["safe", "caution"])
def test_ai_never_executes_or_prompts(monkeypatch, tmp_path, risk_level: str) -> None:
    history_path = tmp_path / "history.json"
    result = AssistantResult(
        command="rm -rf ./build" if risk_level == "caution" else "printf ok",
        explanation="suggested command",
        risk_level=risk_level,
        risk_reason="会删除文件。" if risk_level == "caution" else "",
    )
    monkeypatch.setattr("ai_sh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "ai_sh.cli.create_suggestion",
        lambda *args, **kwargs: _suggestion(tmp_path, result),
    )
    monkeypatch.setattr(
        "ai_sh.cli.HistoryStore",
        lambda limit: HistoryStore(history_path, limit=limit),
    )

    called = {"execute": False, "prompt": False}

    def fake_execute(command: str) -> ExecutionResult:
        called["execute"] = True
        return ExecutionResult(command, 0, "", "")

    def fake_prompt(*args, **kwargs) -> str:
        called["prompt"] = True
        return "y"

    monkeypatch.setattr("ai_sh.cli.execute_command", fake_execute)
    monkeypatch.setattr("ai_sh.cli.prompt_confirm", fake_prompt)

    invocation = CliRunner().invoke(ai, ["suggest", "something"])

    assert invocation.exit_code == 0
    assert called == {"execute": False, "prompt": False}
    assert "建议命令（未执行）" in invocation.output
    entries = HistoryStore(history_path).load_entries()
    assert entries[-1].executed is False


def test_ai_renders_block_without_executing(monkeypatch, tmp_path) -> None:
    blocked = AssistantResult(
        kind="blocked",
        risk_level="danger",
        risk_reason="删除根目录",
    )
    monkeypatch.setattr("ai_sh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "ai_sh.cli.create_suggestion",
        lambda *args, **kwargs: _suggestion(tmp_path, blocked),
    )
    monkeypatch.setattr(
        "ai_sh.cli.execute_command",
        lambda command: pytest.fail("default ai must never execute"),
    )

    invocation = CliRunner().invoke(ai, ["delete", "everything"])

    assert invocation.exit_code == 0
    assert "已拦截危险命令" in invocation.output


def test_ai_dry_run_is_compatible_and_still_never_executes(
    monkeypatch, tmp_path
) -> None:
    history_path = tmp_path / "history.json"
    monkeypatch.setattr("ai_sh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "ai_sh.cli.create_suggestion",
        lambda *args, **kwargs: _suggestion(
            tmp_path,
            AssistantResult(
                command="printf ok", explanation="prints", risk_level="safe"
            ),
        ),
    )
    monkeypatch.setattr(
        "ai_sh.cli.execute_command",
        lambda command: pytest.fail("default ai must never execute"),
    )
    monkeypatch.setattr(
        "ai_sh.cli.HistoryStore",
        lambda limit: HistoryStore(history_path, limit=limit),
    )

    invocation = CliRunner().invoke(ai, ["--dry-run", "say", "hello"])

    assert invocation.exit_code == 0
    assert "建议命令（未执行）" in invocation.output


def test_ai_sh_without_subcommand_shows_legacy_guidance() -> None:
    invocation = CliRunner().invoke(ai_sh)

    assert invocation.exit_code == 0
    assert "ai-sh repl" in invocation.output
    assert "REPL 已启动" not in invocation.output


def test_piped_stdin_is_read_with_a_limit(monkeypatch) -> None:
    class LargeStdin:
        def isatty(self) -> bool:
            return False

        def read(self, size: int) -> str:
            assert size == MAX_STDIN_CONTEXT_CHARS + 1
            return "x" * size

    monkeypatch.setattr("ai_sh.cli.sys.stdin", LargeStdin())

    value = _read_stdin_if_piped()

    assert value.startswith("x" * MAX_STDIN_CONTEXT_CHARS)
    assert value.endswith("...[truncated]")


def test_ai_sh_config_writes_settings(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    monkeypatch.setattr("ai_sh.cli.write_config", _write_config_to(config_path))
    monkeypatch.setattr("ai_sh.cli.load_config", lambda: _config(tmp_path))

    invocation = CliRunner().invoke(
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

    assert invocation.exit_code == 0
    assert "配置已保存" in invocation.output


def test_ai_sh_config_show_redacts_api_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("ai_sh.cli.load_config", lambda: _config(tmp_path))

    invocation = CliRunner().invoke(ai_sh, ["config", "--show"])

    assert invocation.exit_code == 0
    assert "api_key: configured" in invocation.output
    assert "test-key" not in invocation.output


def test_legacy_repl_path_can_execute_and_keeps_conversation(
    monkeypatch, tmp_path
) -> None:
    history = HistoryStore(tmp_path / "history.json", limit=10)
    conversation = Conversation(max_messages=20)
    config = _config(tmp_path, default_confirm="y")
    result = AssistantResult(
        command="printf done",
        explanation="prints done",
        risk_level="safe",
    )
    monkeypatch.setattr(
        "ai_sh.cli.create_suggestion",
        lambda *args, **kwargs: _suggestion(tmp_path, result),
    )
    monkeypatch.setattr(
        "ai_sh.cli.execute_command",
        lambda command: ExecutionResult(command, 0, "done", ""),
    )

    _run_legacy_once(
        "打印 done",
        stdin_context="",
        dry_run=False,
        config=config,
        history=history,
        conversation=conversation,
    )

    assert history.load_entries()[-1].executed is True
    assert "done" in conversation.messages[-1]["content"]


def test_legacy_repl_dry_run_does_not_execute(monkeypatch, tmp_path) -> None:
    history = HistoryStore(tmp_path / "history.json", limit=10)
    result = AssistantResult(
        command="printf no", explanation="prints", risk_level="safe"
    )
    monkeypatch.setattr(
        "ai_sh.cli.create_suggestion",
        lambda *args, **kwargs: _suggestion(tmp_path, result),
    )
    monkeypatch.setattr(
        "ai_sh.cli.execute_command",
        lambda command: pytest.fail("legacy dry-run must not execute"),
    )

    _run_legacy_once(
        "打印 no",
        stdin_context="",
        dry_run=True,
        config=_config(tmp_path),
        history=history,
    )

    assert history.load_entries()[-1].executed is False


def _suggestion(tmp_path, result: AssistantResult) -> Suggestion:
    return Suggestion(result=result, environment={"cwd": str(tmp_path)})


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
