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
    assert "original_buffer (commandline)" in invocation.stdout
    assert 'commandline --replace "$generated_command"' in invocation.stdout
    assert "bind '\\cg' __tmksh_widget" in invocation.stdout
    assert "suggest --input-format nul" in invocation.stdout
    assert "fish_preexec" in invocation.stdout
    assert "fish_postexec" in invocation.stdout
    assert 'TMKSH_LAST_COMMAND ""' in invocation.stdout


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
        (
            "按修改时间排序\n",
            "find src -type f",
            5,
            "find src -type f | sort -nr",
            "safe",
        ),
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


@pytest.mark.skipif(FISH is None, reason="fish is not installed")
def test_fish_widget_displays_multiline_answer_without_inserting_command(
    tmp_path: Path,
) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="answer\n",
        original_buffer="keep --this",
        original_cursor=4,
    )

    assert completed.returncode == 0, completed.stderr
    assert "第一行\n\n第三行" in completed.stdout
    assert "tmksh did not return a command" not in completed.stdout
    assert _line_from_output(completed.stdout) == "keep --this"
    assert _point_from_output(completed.stdout) == 4


@pytest.mark.skipif(FISH is None, reason="fish is not installed")
def test_fish_widget_sends_all_three_clarification_answers(tmp_path: Path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="clarify-three\n答案一\n答案二\n答案三\n",
        original_buffer="keep this",
        original_cursor=4,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.count("需要澄清：") == 3
    assert _line_from_output(completed.stdout) == "clarified with 3 answers"


@pytest.mark.skipif(FISH is None, reason="fish is not installed")
def test_fish_failure_hooks_record_nonzero_command_state() -> None:
    script = render_fish_init(command_path="tmksh", python_path=sys.executable)
    shell_code = r"""
source $argv[1]
__tmksh_capture_command_start 'python missing.py'
set -g TMKSH_PENDING_CWD '/tmp/original cwd'
false
__tmksh_capture_command_end
__tmksh_capture_command_start 'git status --short'
true
__tmksh_capture_command_end
printf '%s\0%s\0%s\0%s\0%s' "$TMKSH_LAST_FAILED_COMMAND" \
    "$TMKSH_LAST_FAILED_STATUS" "$TMKSH_LAST_FAILED_CWD" \
    "$TMKSH_LAST_FAILED_SHELL" "$TMKSH_LAST_COMMAND"
"""
    completed = subprocess.run(
        [FISH, "--no-config", "--command", shell_code, "fish", "/dev/stdin"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.split("\0") == [
        "python missing.py",
        "1",
        "/tmp/original cwd",
        "fish",
        "git status --short",
    ]


@pytest.mark.skipif(FISH is None, reason="fish is not installed")
def test_fish_widget_sends_failure_state_for_fix(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="/fix 不要使用 pip\n",
        original_buffer="keep this",
        original_cursor=4,
        failed_command="python app.py",
        failed_status=1,
        failed_cwd="/tmp/demo project",
    )

    assert completed.returncode == 0, completed.stderr
    assert _line_from_output(completed.stdout) == (
        "fixed[fish:1:/tmp/demo project]: python app.py"
    )


@pytest.mark.skipif(FISH is None, reason="fish is not installed")
def test_fish_widget_sends_last_command_context(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="last-command\n",
        original_buffer="keep this",
        original_cursor=4,
        last_command="git status --short",
    )

    assert completed.returncode == 0, completed.stderr
    assert _line_from_output(completed.stdout) == "last[git status --short]"


@pytest.mark.skipif(FISH is None, reason="fish is not installed")
def test_fish_fix_restores_buffer_for_missing_blocked_and_error(tmp_path) -> None:
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


def _run_widget(
    tmp_path: Path,
    *,
    user_input: str,
    original_buffer: str,
    original_cursor: int,
    failed_command: str = "",
    failed_status: int | None = None,
    failed_cwd: str = "",
    last_command: str = "",
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
set -g TMKSH_LAST_FAILED_COMMAND $argv[4]
set -g TMKSH_LAST_FAILED_STATUS $argv[5]
set -g TMKSH_LAST_FAILED_CWD $argv[6]
set -g TMKSH_LAST_COMMAND $argv[7]
if test -n "$argv[4]"
    set -g TMKSH_LAST_FAILED_SHELL fish
end
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
            failed_command,
            "" if failed_status is None else str(failed_status),
            failed_cwd,
            last_command,
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

parts = sys.stdin.buffer.read().split(b"\\0")
request, buffer, failed_command, failed_status, failed_cwd, failed_shell, last_command = (
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
elif request == "answer":
    response.update(kind="answer", command="rm -rf /", answer="第一行\\n\\n第三行")
elif request == "last-command":
    response.update(command=f"last[{{last_command}}]")
elif "block" in request:
    response.update(kind="blocked", command="", risk_level="danger", risk_reason="删除根目录")
    status = 31
elif "caution" in request:
    response.update(command=buffer + " --interactive", risk_level="caution", risk_reason="会删除文件。")
elif "error" in request:
    response.update(kind="error", command="", error="连接 AI 服务失败")
    status = 21
elif request.startswith("clarify-three"):
    answer_count = request.count("用户补充：")
    if answer_count < 3:
        response.update(
            kind="clarification",
            command="",
            clarification=f"请提供第 {{answer_count + 1}} 个答案。",
        )
        status = 30
    else:
        response.update(command="clarified with 3 answers")
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
    return output.split("__TMKSH_LINE__=", 1)[1].splitlines()[0]


def _point_from_output(output: str) -> int:
    return int(output.split("__TMKSH_POINT__=", 1)[1].splitlines()[0])
