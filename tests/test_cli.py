import pytest
from click.testing import CliRunner

from tmksh.cli import _read_stdin_if_piped, tmksh
from tmksh.protocol import MAX_STDIN_CONTEXT_CHARS
from tmksh.history import HistoryStore
from tmksh.llm import AssistantResult
from tmksh.suggestion import Suggestion


@pytest.mark.parametrize("risk_level", ["safe", "caution"])
def test_tmksh_never_executes_or_prompts(
    monkeypatch, tmp_path, risk_level: str
) -> None:
    history_path = tmp_path / "history.json"
    result = AssistantResult(
        command="rm -rf ./build" if risk_level == "caution" else "printf ok",
        explanation="suggested command",
        risk_level=risk_level,
        risk_reason="会删除文件。" if risk_level == "caution" else "",
    )
    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "tmksh.cli.create_suggestion",
        lambda *args, **kwargs: _suggestion(tmp_path, result),
    )
    monkeypatch.setattr(
        "tmksh.cli.HistoryStore",
        lambda limit: HistoryStore(history_path, limit=limit),
    )

    invocation = CliRunner().invoke(tmksh, ["suggest something"])

    assert invocation.exit_code == 0
    assert "建议命令（未执行）" in invocation.output
    entries = HistoryStore(history_path).load_entries()
    assert entries[-1].command == result.command


def test_tmksh_renders_block_without_executing(monkeypatch, tmp_path) -> None:
    blocked = AssistantResult(
        kind="blocked",
        risk_level="danger",
        risk_reason="删除根目录",
    )
    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "tmksh.cli.create_suggestion",
        lambda *args, **kwargs: _suggestion(tmp_path, blocked),
    )
    invocation = CliRunner().invoke(tmksh, ["delete", "everything"])

    assert invocation.exit_code == 0
    assert "已拦截危险命令" in invocation.output


def test_tmksh_ask_returns_plain_text_for_piped_diff(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))
    captured = {}

    def fake_answer(config, question, **kwargs):
        captured.update(question=question, **kwargs)
        return "修改了命令行入口。"

    monkeypatch.setattr("tmksh.cli.create_answer", fake_answer)
    monkeypatch.setattr(
        "tmksh.cli.create_suggestion",
        lambda *args, **kwargs: pytest.fail("ask must not generate a command"),
    )
    monkeypatch.setattr(
        "tmksh.cli.HistoryStore",
        lambda *args, **kwargs: pytest.fail("ask must not access history"),
    )

    invocation = CliRunner().invoke(
        tmksh,
        ["ask", "总结这些修改"],
        input="diff --git a/src/cli.py b/src/cli.py\n",
    )

    assert invocation.exit_code == 0
    assert invocation.output == "修改了命令行入口。\n"
    assert captured["question"] == "总结这些修改"
    assert "diff --git" in captured["stdin_context"]
    assert captured["stdin_truncated"] is False


def test_tmksh_ask_supports_question_without_stdin(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr("tmksh.cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        "tmksh.cli.create_answer",
        lambda config, question, **kwargs: "Git rebase 会重写提交历史。",
    )

    invocation = CliRunner().invoke(tmksh, ["ask", "什么是 git rebase？"])

    assert invocation.exit_code == 0
    assert invocation.output == "Git rebase 会重写提交历史。\n"


def test_tmksh_ask_failure_is_nonzero_and_understandable(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr("tmksh.cli.sys.stdin.isatty", lambda: True)

    def fail(*args, **kwargs):
        from tmksh.exceptions import ApiError

        raise ApiError("服务暂时不可用，credential=test-key")

    monkeypatch.setattr("tmksh.cli.create_answer", fail)

    invocation = CliRunner().invoke(tmksh, ["ask", "分析报错"])

    assert invocation.exit_code == 1
    assert "错误：服务暂时不可用" in invocation.output
    assert "test-key" not in invocation.output
    assert "[redacted]" in invocation.output


def test_tmksh_ask_reports_truncated_log_input(monkeypatch, tmp_path) -> None:
    from tmksh.answer import MAX_ASK_STDIN_BYTES

    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))
    captured = {}

    def fake_answer(config, question, **kwargs):
        captured.update(kwargs)
        return "日志分析完成。"

    monkeypatch.setattr("tmksh.cli.create_answer", fake_answer)

    invocation = CliRunner().invoke(
        tmksh,
        ["ask", "分析日志"],
        input="E" * (MAX_ASK_STDIN_BYTES + 1),
    )

    assert invocation.exit_code == 0
    assert "stdin 超过 65536 字节" in invocation.output
    assert "日志分析完成。" in invocation.output
    assert len(captured["stdin_context"].encode()) == MAX_ASK_STDIN_BYTES
    assert captured["stdin_truncated"] is True


def test_tmksh_ask_rejects_command_options() -> None:
    invocation = CliRunner().invoke(tmksh, ["ask", "--json", "回答问题"])

    assert invocation.exit_code == 2
    assert "No such option '--json'" in invocation.output


def test_tmksh_without_subcommand_shows_unified_help() -> None:
    invocation = CliRunner().invoke(tmksh)

    assert invocation.exit_code == 0
    assert "Commands:" in invocation.output
    assert "ask" in invocation.output
    assert "config" in invocation.output
    assert "REPL 已启动" not in invocation.output


def test_tmksh_reports_package_version() -> None:
    invocation = CliRunner().invoke(tmksh, ["--version"])

    assert invocation.exit_code == 0
    assert invocation.output == "tmksh, version 0.2.0\n"


def test_piped_stdin_is_read_with_a_limit(monkeypatch) -> None:
    class LargeStdin:
        def isatty(self) -> bool:
            return False

        def read(self, size: int) -> str:
            assert size == MAX_STDIN_CONTEXT_CHARS + 1
            return "x" * size

    monkeypatch.setattr("tmksh.cli.sys.stdin", LargeStdin())

    value = _read_stdin_if_piped()

    assert value.startswith("x" * MAX_STDIN_CONTEXT_CHARS)
    assert value.endswith("...[truncated]")


def test_tmksh_config_writes_settings(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    monkeypatch.setattr("tmksh.cli.write_config", _write_config_to(config_path))
    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))

    invocation = CliRunner().invoke(
        tmksh,
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


def test_tmksh_config_show_redacts_api_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))

    invocation = CliRunner().invoke(tmksh, ["config", "--show"])

    assert invocation.exit_code == 0
    assert "api_key: configured" in invocation.output
    assert "test-key" not in invocation.output


def _suggestion(tmp_path, result: AssistantResult) -> Suggestion:
    return Suggestion(result=result, environment={"cwd": str(tmp_path)})


def _config(tmp_path):
    from tmksh.config import ApiConfig, BehaviorConfig, Config

    return Config(
        api=ApiConfig(api_key="test-key"),
        behavior=BehaviorConfig(history_limit=10),
        path=tmp_path / "config.toml",
    )


def _write_config_to(config_path):
    from tmksh.config import write_config as real_write_config

    def write_to_temp(**kwargs):
        kwargs["path"] = config_path
        return real_write_config(**kwargs)

    return write_to_temp
