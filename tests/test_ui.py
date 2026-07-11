from tmksh import ui
from tmksh.llm import AssistantResult


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
