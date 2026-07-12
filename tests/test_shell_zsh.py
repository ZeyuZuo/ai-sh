import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from tmksh.cli import tmksh
from tmksh.shell import render_bash_init, render_fish_init, render_zsh_init

ZSH = shutil.which("zsh")


def test_zsh_init_command_outputs_zle_script() -> None:
    invocation = CliRunner().invoke(tmksh, ["init", "zsh"])

    assert invocation.exit_code == 0
    assert "__tmksh_widget" in invocation.stdout
    assert 'original_buffer="$BUFFER"' in invocation.stdout
    assert "zle -N __tmksh_widget" in invocation.stdout
    assert "bindkey '^G' __tmksh_widget" in invocation.stdout
    assert "suggest --input-format nul" in invocation.stdout
    assert "__tmksh_capture_command_start" in invocation.stdout
    assert "__tmksh_capture_command_end" in invocation.stdout


def test_zsh_init_supports_custom_binding_and_quoted_path() -> None:
    script = render_zsh_init(
        key_binding="^[a",
        command_path="/opt/tmk sh/bin/tmksh",
        python_path="/opt/python/bin/python",
    )

    assert "bindkey '^[a' __tmksh_widget" in script
    assert "'/opt/tmk sh/bin/tmksh'" in script


def test_shell_widgets_share_protocol_and_safety_semantics() -> None:
    scripts = [
        render_bash_init(command_path="tmksh", python_path="python3"),
        render_zsh_init(command_path="tmksh", python_path="python3"),
        render_fish_init(command_path="tmksh", python_path="python3"),
    ]

    for script in scripts:
        assert "suggest --input-format nul" in script
        assert "printf '%s\\0%s\\0%s\\0%s\\0%s\\0%s'" in script
        assert "LAST_FAILED_COMMAND" in script
        assert "LAST_FAILED_STATUS" in script
        assert "LAST_FAILED_CWD" in script
        assert any(
            marker in script
            for marker in ("status == 0", "exit_status == 0", "$exit_status -eq 0")
        )
        assert any(
            marker in script
            for marker in ("status == 30", "exit_status == 30", "$exit_status -eq 30")
        )
        assert ("attempts < 3" in script) or ("$attempts -lt 3" in script)
        assert "risk_reason" in script
        assert "eval " not in script
    assert 'original_point="$READLINE_POINT"' in scripts[0]
    assert 'READLINE_POINT="$original_point"' in scripts[0]
    assert "original_cursor=$CURSOR" in scripts[1]
    assert "CURSOR=$original_cursor" in scripts[1]
    assert "original_buffer (commandline)" in scripts[2]
    assert 'commandline --replace "$original_buffer"' in scripts[2]


@pytest.mark.skipif(ZSH is None, reason="zsh is not installed")
def test_zsh_init_script_passes_native_syntax_check() -> None:
    script = render_zsh_init(command_path="tmksh", python_path=sys.executable)

    syntax = subprocess.run(
        [ZSH, "-n"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )

    assert syntax.returncode == 0, syntax.stderr


@pytest.mark.skipif(ZSH is None, reason="zsh is not installed")
def test_zsh_widget_replaces_buffer_and_handles_clarification(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="clarify\n./src\n",
        original_buffer="find .",
    )

    assert completed.returncode == 0, completed.stderr
    assert "需要澄清：请提供目录。" in completed.stdout
    expected = "find . ./src"
    assert _line_from_output(completed.stdout) == expected
    assert _point_from_output(completed.stdout) == len(expected)


@pytest.mark.skipif(ZSH is None, reason="zsh is not installed")
def test_zsh_widget_shows_caution_and_only_fills_buffer(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="caution\n",
        original_buffer="rm -rf ./build",
    )

    assert completed.returncode == 0, completed.stderr
    assert "caution · 会删除文件。" in completed.stdout
    assert _line_from_output(completed.stdout) == "rm -rf ./build --interactive"


@pytest.mark.skipif(ZSH is None, reason="zsh is not installed")
def test_zsh_widget_restores_buffer_when_blocked(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="block\n",
        original_buffer="keep --this",
        original_cursor=4,
    )

    assert completed.returncode == 0, completed.stderr
    assert "删除根目录" in completed.stdout
    assert _line_from_output(completed.stdout) == "keep --this"
    assert _point_from_output(completed.stdout) == 4


@pytest.mark.skipif(ZSH is None, reason="zsh is not installed")
def test_zsh_widget_restores_buffer_and_cursor_on_api_error(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="error\n",
        original_buffer="git status --short",
        original_cursor=3,
    )

    assert completed.returncode == 0, completed.stderr
    assert "连接 AI 服务失败" in completed.stdout
    assert _line_from_output(completed.stdout) == "git status --short"
    assert _point_from_output(completed.stdout) == 3


@pytest.mark.skipif(ZSH is None, reason="zsh is not installed")
def test_zsh_failure_hooks_record_nonzero_command_state() -> None:
    script = render_zsh_init(command_path="tmksh", python_path=sys.executable)
    shell_code = r"""
source "$1"
__tmksh_capture_command_start 'python missing.py'
TMKSH_PENDING_CWD='/tmp/original cwd'
(exit 7)
__tmksh_capture_command_end
print -rn -- "$TMKSH_LAST_FAILED_COMMAND\0$TMKSH_LAST_FAILED_STATUS\0$TMKSH_LAST_FAILED_CWD\0$TMKSH_LAST_FAILED_SHELL"
"""
    completed = subprocess.run(
        [ZSH, "-f", "-c", shell_code, "zsh", "/dev/stdin"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.split("\0") == [
        "python missing.py",
        "7",
        "/tmp/original cwd",
        "zsh",
    ]


@pytest.mark.skipif(ZSH is None, reason="zsh is not installed")
def test_zsh_widget_sends_failure_state_for_fix(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="/fix 不要使用 pip\n",
        original_buffer="keep this",
        failed_command="python app.py",
        failed_status=1,
        failed_cwd="/tmp/demo project",
    )

    assert completed.returncode == 0, completed.stderr
    assert _line_from_output(completed.stdout) == (
        "fixed[zsh:1:/tmp/demo project]: python app.py"
    )


@pytest.mark.skipif(ZSH is None, reason="zsh is not installed")
def test_zsh_fix_restores_buffer_for_missing_blocked_and_error(tmp_path) -> None:
    cases = (
        ("/fix\n", "", "没有找到最近失败的命令"),
        ("/fix block\n", "bad command", "删除根目录"),
        ("/fix error\n", "bad command", "连接 AI 服务失败"),
    )
    for request, failed_command, expected_message in cases:
        completed = _run_widget(
            tmp_path,
            user_input=request,
            original_buffer="keep this",
            original_cursor=4,
            failed_command=failed_command,
            failed_status=1 if failed_command else None,
            failed_cwd="/tmp/demo" if failed_command else "",
        )

        assert completed.returncode == 0, completed.stderr
        assert expected_message in completed.stdout
        assert _line_from_output(completed.stdout) == "keep this"
        assert _point_from_output(completed.stdout) == 4


@pytest.mark.skipif(ZSH is None, reason="zsh is not installed")
def test_zsh_widget_restores_buffer_when_cancelled(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="\n",
        original_buffer="keep this",
        original_cursor=4,
    )

    assert completed.returncode == 0, completed.stderr
    assert _line_from_output(completed.stdout) == "keep this"
    assert _point_from_output(completed.stdout) == 4


def _run_widget(
    tmp_path: Path,
    *,
    user_input: str,
    original_buffer: str,
    original_cursor: int | None = None,
    failed_command: str = "",
    failed_status: int | None = None,
    failed_cwd: str = "",
) -> subprocess.CompletedProcess[str]:
    assert ZSH is not None
    backend = _write_fake_backend(tmp_path)
    init_path = tmp_path / "zsh-init.zsh"
    init_path.write_text(
        render_zsh_init(
            command_path=str(backend),
            python_path=sys.executable,
        ),
        encoding="utf-8",
    )
    shell_code = r"""
source "$1"
BUFFER="$2"
CURSOR=$3
TMKSH_LAST_FAILED_COMMAND="$4"
TMKSH_LAST_FAILED_STATUS="$5"
TMKSH_LAST_FAILED_CWD="$6"
TMKSH_LAST_FAILED_SHELL="${4:+zsh}"
__tmksh_widget
print -r -- "__TMKSH_LINE__=$BUFFER"
print -r -- "__TMKSH_POINT__=$CURSOR"
"""
    return subprocess.run(
        [
            ZSH,
            "-f",
            "-c",
            shell_code,
            "zsh",
            str(init_path),
            original_buffer,
            str(len(original_buffer) if original_cursor is None else original_cursor),
            failed_command,
            "" if failed_status is None else str(failed_status),
            failed_cwd,
        ],
        input=user_input,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_fake_backend(tmp_path: Path) -> Path:
    path = tmp_path / "fake-tmksh"
    script = f"""#!{sys.executable}
import json
import sys

parts = sys.stdin.buffer.read().split(b"\\0")
request, buffer, failed_command, failed_status, failed_cwd, failed_shell = (
    part.decode() for part in parts
)
response = {{
    "protocol_version": 1,
    "kind": "command",
    "command": buffer + " | sort -nr",
    "answer": "",
    "explanation": "generated safely",
    "risk_level": "safe",
    "risk_reason": "",
    "clarification": "",
    "error": "",
}}
status = 0
if request.lower().startswith("/fix") and not failed_command:
    response.update(kind="error", command="", error="没有找到最近失败的命令")
    status = 32
elif request.lower().startswith("/fix") and "block" in request:
    response.update(kind="blocked", command="", risk_level="danger", risk_reason="删除根目录")
    status = 31
elif request.lower().startswith("/fix") and "error" in request:
    response.update(kind="error", command="", error="连接 AI 服务失败")
    status = 21
elif request.lower().startswith("/fix"):
    response.update(
        command=f"fixed[{{failed_shell}}:{{failed_status}}:{{failed_cwd}}]: {{failed_command}}"
    )
elif "block" in request:
    response.update(kind="blocked", command="", risk_level="danger", risk_reason="删除根目录")
    status = 31
elif "caution" in request:
    response.update(command=buffer + " --interactive", risk_level="caution", risk_reason="会删除文件。")
elif "error" in request:
    response.update(kind="error", command="", error="连接 AI 服务失败")
    status = 21
elif "clarify" in request and "用户补充" not in request:
    response.update(kind="clarification", command="", clarification="请提供目录。")
    status = 30
elif "clarify" in request:
    answer = request.rsplit("用户补充：", 1)[1]
    response.update(command=buffer + " " + answer)
print(json.dumps(response, ensure_ascii=False))
raise SystemExit(status)
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(0o700)
    return path


def _line_from_output(output: str) -> str:
    marker = "__TMKSH_LINE__="
    return output.split(marker, 1)[1].splitlines()[0]


def _point_from_output(output: str) -> int:
    marker = "__TMKSH_POINT__="
    return int(output.split(marker, 1)[1].splitlines()[0])
