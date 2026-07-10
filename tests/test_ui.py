from ai_sh import ui
from ai_sh.executor import ExecutionResult
from ai_sh.llm import AssistantResult


def test_prompt_confirm_cancel_on_eof(monkeypatch) -> None:
    class EmptyStdin:
        def readline(self):
            return ""

    monkeypatch.setattr(ui.sys, "stdin", EmptyStdin())

    assert ui.prompt_confirm() == "n"


def test_prompt_confirm_accepts_y(monkeypatch) -> None:
    class FakeStdin:
        def readline(self):
            return "y\n"

    monkeypatch.setattr(ui.sys, "stdin", FakeStdin())

    assert ui.prompt_confirm() == "y"


def test_prompt_confirm_describes_choices(monkeypatch, capsys) -> None:
    class FakeStdin:
        def readline(self):
            return "n\n"

    monkeypatch.setattr(ui.sys, "stdin", FakeStdin())

    assert ui.prompt_confirm() == "n"
    output = capsys.readouterr().out
    assert "输入 y 执行" in output
    assert "输入 e 先编辑" in output
    assert "输入 n 取消" in output


def test_render_execution_result_explains_empty_output(capsys) -> None:
    ui.render_execution_result(
        ExecutionResult(
            command="find . -type f -size +100M", exit_code=0, stdout="", stderr=""
        )
    )

    output = capsys.readouterr().out
    assert "命令已成功执行" in output
    assert "没有输出" in output
    assert "已执行命令" in output


def test_render_command_shows_plan_context(capsys) -> None:
    ui.render_command(
        AssistantResult(
            command="find . -type f -size +100M",
            explanation="查找大文件",
            risk_level="safe",
        ),
        cwd="/tmp/project",
    )

    output = capsys.readouterr().out
    assert "建议命令（未执行）" in output
    assert "/tmp/project" in output
    assert "safe（只读或低风险）" in output


def test_render_result_shows_block(capsys) -> None:
    ui.render_result(
        AssistantResult(kind="blocked", risk_level="danger", risk_reason="删除根目录")
    )

    output = capsys.readouterr().out
    assert "已拦截危险命令" in output
