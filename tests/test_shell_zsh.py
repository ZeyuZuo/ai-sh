import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from tmksh.cli import tmksh
from tmksh.shell import render_bash_init, render_zsh_init

ZSH = shutil.which("zsh")


def test_zsh_init_command_outputs_zle_script() -> None:
    invocation = CliRunner().invoke(tmksh, ["init", "zsh"])

    assert invocation.exit_code == 0
    assert "__tmksh_widget" in invocation.stdout
    assert 'original_buffer="$BUFFER"' in invocation.stdout
    assert "zle -N __tmksh_widget" in invocation.stdout
    assert "bindkey '^G' __tmksh_widget" in invocation.stdout
    assert "suggest --input-format nul" in invocation.stdout


def test_zsh_init_supports_custom_binding_and_quoted_path() -> None:
    script = render_zsh_init(
        key_binding="^[a",
        command_path="/opt/tmk sh/bin/tmksh",
        python_path="/opt/python/bin/python",
    )

    assert "bindkey '^[a' __tmksh_widget" in script
    assert "'/opt/tmk sh/bin/tmksh'" in script


def test_bash_and_zsh_widgets_share_protocol_and_safety_semantics() -> None:
    scripts = [
        render_bash_init(command_path="tmksh", python_path="python3"),
        render_zsh_init(command_path="tmksh", python_path="python3"),
    ]

    for script in scripts:
        assert "suggest --input-format nul" in script
        assert "printf '%s\\0%s'" in script
        assert ("status == 0" in script) or ("exit_status == 0" in script)
        assert ("status == 30" in script) or ("exit_status == 30" in script)
        assert "attempts < 3" in script
        assert "risk_reason" in script
        assert "eval " not in script
    assert 'original_point="$READLINE_POINT"' in scripts[0]
    assert 'READLINE_POINT="$original_point"' in scripts[0]
    assert "original_cursor=$CURSOR" in scripts[1]
    assert "CURSOR=$original_cursor" in scripts[1]


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


def _run_widget(
    tmp_path: Path,
    *,
    user_input: str,
    original_buffer: str,
    original_cursor: int | None = None,
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

request_bytes, buffer_bytes = sys.stdin.buffer.read().split(b"\\0", 1)
request = request_bytes.decode()
buffer = buffer_bytes.decode()
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
if "block" in request:
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
