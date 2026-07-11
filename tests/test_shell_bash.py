import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from tmksh.cli import tmksh
from tmksh.shell import render_bash_init


def test_bash_init_command_outputs_loadable_script() -> None:
    invocation = CliRunner().invoke(tmksh, ["init", "bash"])

    assert invocation.exit_code == 0
    assert "__tmksh_widget" in invocation.stdout
    assert "READLINE_LINE" in invocation.stdout
    assert "bind -x" in invocation.stdout
    assert "suggest --input-format nul" in invocation.stdout
    assert '_prompt --label "$prompt"' in invocation.stdout

    syntax = subprocess.run(
        ["bash", "-n"],
        input=invocation.stdout,
        text=True,
        capture_output=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr


def test_bash_init_supports_custom_binding() -> None:
    script = render_bash_init(
        key_binding=r"\C-x\C-a",
        command_path="/opt/tmk sh/bin/tmksh",
        python_path="/opt/python/bin/python",
    )

    assert r'"\C-x\C-a":__tmksh_widget' in script
    assert "'/opt/tmk sh/bin/tmksh'" in script


def test_internal_widget_prompt_falls_back_to_stdin() -> None:
    invocation = CliRunner().invoke(
        tmksh,
        ["_prompt", "--label", "tmksh> "],
        input="测试输入\n",
    )

    assert invocation.exit_code == 0
    assert invocation.stdout == "测试输入\n"
    assert invocation.stderr == "tmksh> "


def test_bash_widget_replaces_buffer_without_executing(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="按修改时间排序\n",
        original_line="find src -type f",
    )

    assert completed.returncode == 0, completed.stderr
    assert "safe · generated safely" in completed.stdout
    expected = "find src -type f | sort -nr"
    assert _line_from_output(completed.stdout) == expected
    assert _point_from_output(completed.stdout) == len(expected)


def test_bash_widget_shows_caution_and_only_fills_buffer(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="caution\n",
        original_line="rm -rf ./build",
    )

    assert completed.returncode == 0, completed.stderr
    assert "caution · 会删除文件。" in completed.stdout
    assert _line_from_output(completed.stdout) == "rm -rf ./build --interactive"


def test_bash_widget_restores_buffer_when_blocked_or_cancelled(tmp_path) -> None:
    blocked = _run_widget(
        tmp_path,
        user_input="block\n",
        original_line="keep --this",
        original_point=4,
    )
    cancelled = _run_widget(
        tmp_path,
        user_input="\n",
        original_line="keep --this",
        original_point=4,
    )

    assert "删除根目录" in blocked.stdout
    assert _line_from_output(blocked.stdout) == "keep --this"
    assert _point_from_output(blocked.stdout) == 4
    assert _line_from_output(cancelled.stdout) == "keep --this"
    assert _point_from_output(cancelled.stdout) == 4


def test_bash_widget_restores_buffer_and_cursor_on_api_error(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="error\n",
        original_line="git status --short",
        original_point=3,
    )

    assert "连接 AI 服务失败" in completed.stdout
    assert _line_from_output(completed.stdout) == "git status --short"
    assert _point_from_output(completed.stdout) == 3


def test_bash_widget_handles_clarification_in_same_interaction(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="clarify\n./src\n",
        original_line="find .",
    )

    assert completed.returncode == 0, completed.stderr
    assert "需要澄清：请提供目录。" in completed.stdout
    assert _line_from_output(completed.stdout) == "find . ./src"


def _run_widget(
    tmp_path: Path,
    *,
    user_input: str,
    original_line: str,
    original_point: int | None = None,
) -> subprocess.CompletedProcess[str]:
    backend = _write_fake_backend(tmp_path)
    init_path = tmp_path / "bash-init.sh"
    init_path.write_text(
        render_bash_init(
            command_path=str(backend),
            python_path=sys.executable,
        ),
        encoding="utf-8",
    )
    shell_code = r"""
source "$1"
READLINE_LINE="$2"
READLINE_POINT=$3
__tmksh_widget
printf '\n__TMKSH_LINE__=%s\n' "$READLINE_LINE"
printf '__TMKSH_POINT__=%s\n' "$READLINE_POINT"
"""
    return subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            shell_code,
            "bash",
            str(init_path),
            original_line,
            str(len(original_line) if original_point is None else original_point),
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
import os
import sys

if len(sys.argv) > 1 and sys.argv[1] == "_prompt":
    value = bytearray()
    while True:
        character = os.read(0, 1)
        if not character or character in {{b"\\n", b"\\r"}}:
            break
        value.extend(character)
    print(value.decode())
    raise SystemExit(0)

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
