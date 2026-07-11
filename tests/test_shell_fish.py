import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from tmksh.cli import tmksh
from tmksh.shell import render_fish_init

FISH = shutil.which("fish")


def test_fish_init_command_outputs_commandline_script() -> None:
    invocation = CliRunner().invoke(tmksh, ["init", "fish"])

    assert invocation.exit_code == 0
    assert "__tmksh_widget" in invocation.stdout
    assert 'original_buffer (commandline)' in invocation.stdout
    assert 'commandline --replace "$generated_command"' in invocation.stdout
    assert "bind '\\cg' __tmksh_widget" in invocation.stdout
    assert "suggest --input-format nul" in invocation.stdout


def test_fish_init_supports_custom_binding_and_quoted_path() -> None:
    script = render_fish_init(
        key_binding=r"\cx\ca",
        command_path="/opt/tmk sh/bin/tmksh",
        python_path="/opt/python/bin/python",
    )

    assert "bind '\\cx\\ca' __tmksh_widget" in script
    assert "'/opt/tmk sh/bin/tmksh'" in script


@pytest.mark.skipif(FISH is None, reason="fish is not installed")
def test_fish_init_script_passes_native_syntax_check() -> None:
    script = render_fish_init(command_path="tmksh", python_path=sys.executable)

    syntax = subprocess.run(
        [FISH, "--no-execute"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )

    assert syntax.returncode == 0, syntax.stderr


@pytest.mark.skipif(FISH is None, reason="fish is not installed")
@pytest.mark.parametrize(
    ("user_input", "original", "cursor", "expected", "message"),
    [
        ("按修改时间排序\n", "find src -type f", 5, "find src -type f | sort -nr", "safe"),
        ("caution\n", "rm -rf ./build", 4, "rm -rf ./build --interactive", "caution"),
        ("block\n", "keep --this", 4, "keep --this", "删除根目录"),
        ("error\n", "git status --short", 3, "git status --short", "连接 AI 服务失败"),
        ("clarify\n./src\n", "find .", 2, "find . ./src", "需要澄清"),
        ("\n", "keep --this", 4, "keep --this", ""),
    ],
)
def test_fish_widget_preserves_protocol_and_buffer_semantics(
    tmp_path: Path,
    user_input: str,
    original: str,
    cursor: int,
    expected: str,
    message: str,
) -> None:
    completed = _run_widget(
        tmp_path,
        user_input=user_input,
        original_buffer=original,
        original_cursor=cursor,
    )

    assert completed.returncode == 0, completed.stderr
    assert _line_from_output(completed.stdout) == expected
    expected_cursor = len(expected) if expected != original else cursor
    assert _point_from_output(completed.stdout) == expected_cursor
    assert message in completed.stdout


def _run_widget(
    tmp_path: Path,
    *,
    user_input: str,
    original_buffer: str,
    original_cursor: int,
) -> subprocess.CompletedProcess[str]:
    assert FISH is not None
    backend = _write_fake_backend(tmp_path)
    init_path = tmp_path / "fish-init.fish"
    init_path.write_text(
        render_fish_init(command_path=str(backend), python_path=sys.executable),
        encoding="utf-8",
    )
    shell_code = r"""
set -g TEST_LINE $argv[2]
set -g TEST_POINT $argv[3]
source $argv[1]
function commandline
    if test (count $argv) -eq 0
        printf '%s' "$TEST_LINE"
    else if test "$argv[1]" = '--cursor'
        if test (count $argv) -eq 1
            printf '%s' "$TEST_POINT"
        else
            set -g TEST_POINT $argv[2]
        end
    else if test "$argv[1]" = '--replace'
        set -g TEST_LINE $argv[2]
    end
end
__tmksh_widget
printf '\n__TMKSH_LINE__=%s\n' "$TEST_LINE"
printf '__TMKSH_POINT__=%s\n' "$TEST_POINT"
"""
    return subprocess.run(
        [
            FISH,
            "--no-config",
            "--command",
            shell_code,
            "fish",
            str(init_path),
            original_buffer,
            str(original_cursor),
        ],
        input=user_input,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_fake_backend(tmp_path: Path) -> Path:
    path = tmp_path / "fake-tmksh"
    script = f'''#!{sys.executable}
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
'''
    path.write_text(script, encoding="utf-8")
    path.chmod(0o700)
    return path


def _line_from_output(output: str) -> str:
    return output.split("__TMKSH_LINE__=", 1)[1].splitlines()[0]


def _point_from_output(output: str) -> int:
    return int(output.split("__TMKSH_POINT__=", 1)[1].splitlines()[0])
