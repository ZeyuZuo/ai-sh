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
    assert "__tmksh_capture_failed_command" in invocation.stdout
    assert "__tmksh_sync_history_state" in invocation.stdout
    assert "PROMPT_COMMAND" in invocation.stdout
    assert 'TMKSH_LAST_FAILED_COMMAND=""' in invocation.stdout
    assert 'TMKSH_LAST_SEEN_HISTORY_COMMAND=""' in invocation.stdout

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


def test_bash_failure_hook_records_current_interactive_command(tmp_path) -> None:
    completed = _run_interactive_bash(
        tmp_path,
        after_init="""
__tmksh_missing_command__
printf '\n__TMKSH_STATE__=%s\\0%s\\0%s\\0%s\n' "$TMKSH_LAST_FAILED_COMMAND" "$TMKSH_LAST_FAILED_STATUS" "$TMKSH_LAST_FAILED_CWD" "$TMKSH_LAST_FAILED_SHELL"
""",
    )

    assert completed.returncode == 0, completed.stderr
    state = completed.stdout.split("__TMKSH_STATE__=", 1)[1].splitlines()[0]
    assert state.split("\0") == [
        "__tmksh_missing_command__",
        "127",
        str(tmp_path),
        "bash",
    ]


def test_bash_failure_hook_handles_erasedups_history_number_reuse(tmp_path) -> None:
    completed = _run_interactive_bash(
        tmp_path,
        before_init="""HISTCONTROL=ignoreboth:erasedups
__tmksh_existing_prompt_hook() { return 0; }
PROMPT_COMMAND=(__tmksh_existing_prompt_hook)
__tmksh_repeated_missing__
""",
        after_init="""__tmksh_repeated_missing__
printf '\n__TMKSH_STATE__=%s\\0%s\\0%s\\0%s\n' "$TMKSH_LAST_FAILED_COMMAND" "$TMKSH_LAST_FAILED_STATUS" "$TMKSH_LAST_FAILED_CWD" "$TMKSH_LAST_FAILED_SHELL"
printf '__TMKSH_PROMPT__=%s\\0%s\\0%s\n' "${PROMPT_COMMAND[0]}" "${PROMPT_COMMAND[1]}" "${PROMPT_COMMAND[2]}"
""",
    )

    assert completed.returncode == 0, completed.stderr
    state = completed.stdout.split("__TMKSH_STATE__=", 1)[1].splitlines()[0]
    assert state.split("\0") == [
        "__tmksh_repeated_missing__",
        "127",
        str(tmp_path),
        "bash",
    ]
    prompt = completed.stdout.split("__TMKSH_PROMPT__=", 1)[1].splitlines()[0]
    assert prompt.split("\0") == [
        "__tmksh_capture_failed_command",
        "__tmksh_existing_prompt_hook",
        "__tmksh_sync_history_state",
    ]


def test_bash_failure_hook_syncs_history_after_existing_prompt_hooks(
    tmp_path,
) -> None:
    completed = _run_interactive_bash(
        tmp_path,
        before_init="""HISTCONTROL=ignorespace
__tmksh_existing_prompt_hook() {
    if [[ -n "${TMKSH_INJECT_HISTORY:-}" ]]; then
        history -s "$TMKSH_INJECT_HISTORY"
        TMKSH_INJECT_HISTORY=""
    fi
}
PROMPT_COMMAND=(__tmksh_existing_prompt_hook)
""",
        after_init="""TMKSH_INJECT_HISTORY='external command'
 __tmksh_ignored_missing_command__
printf '\n__TMKSH_STATE__=%s\\0%s\n' "$TMKSH_LAST_FAILED_COMMAND" "$TMKSH_LAST_FAILED_STATUS"
""",
    )

    assert completed.returncode == 0, completed.stderr
    state = completed.stdout.split("__TMKSH_STATE__=", 1)[1].splitlines()[0]
    assert state.split("\0") == ["", ""]


def test_bash_failure_hook_does_not_pair_old_history_with_ignored_command(
    tmp_path,
) -> None:
    completed = _run_interactive_bash(
        tmp_path,
        before_init="HISTCONTROL=ignorespace",
        after_init="""
 __tmksh_ignored_missing_command__
printf '\n__TMKSH_STATE__=%s\\0%s\n' "$TMKSH_LAST_FAILED_COMMAND" "$TMKSH_LAST_FAILED_STATUS"
""",
    )

    assert completed.returncode == 0, completed.stderr
    state = completed.stdout.split("__TMKSH_STATE__=", 1)[1].splitlines()[0]
    assert state.split("\0") == ["", ""]


def test_bash_widget_sends_failure_state_for_fix(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="/fix 不要使用 pip\n",
        original_line="keep this",
        failed_command="python app.py",
        failed_status=1,
        failed_cwd="/tmp/demo project",
    )

    assert completed.returncode == 0, completed.stderr
    assert _line_from_output(completed.stdout) == (
        "fixed[bash:1:/tmp/demo project]: python app.py"
    )


def test_bash_fix_restores_buffer_without_failure_state(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="/fix\n",
        original_line="keep this",
        original_point=4,
    )

    assert "没有找到最近失败的命令" in completed.stdout
    assert _line_from_output(completed.stdout) == "keep this"
    assert _point_from_output(completed.stdout) == 4


def test_bash_fix_restores_buffer_when_blocked_or_api_fails(tmp_path) -> None:
    for request, expected_message in (
        ("/fix block\n", "删除根目录"),
        ("/fix error\n", "连接 AI 服务失败"),
    ):
        completed = _run_widget(
            tmp_path,
            user_input=request,
            original_line="keep this",
            original_point=4,
            failed_command="bad command",
            failed_status=1,
            failed_cwd="/tmp/demo",
        )

        assert expected_message in completed.stdout
        assert _line_from_output(completed.stdout) == "keep this"
        assert _point_from_output(completed.stdout) == 4


def _run_widget(
    tmp_path: Path,
    *,
    user_input: str,
    original_line: str,
    original_point: int | None = None,
    failed_command: str = "",
    failed_status: int | None = None,
    failed_cwd: str = "",
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
TMKSH_LAST_FAILED_COMMAND="$4"
TMKSH_LAST_FAILED_STATUS="$5"
TMKSH_LAST_FAILED_CWD="$6"
TMKSH_LAST_FAILED_SHELL="${4:+bash}"
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
            failed_command,
            "" if failed_status is None else str(failed_status),
            failed_cwd,
        ],
        input=user_input,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_interactive_bash(
    tmp_path: Path,
    *,
    after_init: str,
    before_init: str = "",
) -> subprocess.CompletedProcess[str]:
    init_path = tmp_path / "bash-init.sh"
    init_path.write_text(
        render_bash_init(command_path="tmksh", python_path=sys.executable),
        encoding="utf-8",
    )
    commands = "\n".join(
        part
        for part in (before_init, f"source {init_path!s}", after_init, "exit")
        if part
    )
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-i"],
        input=commands + "\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=tmp_path,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "PS1": "", "PS2": ""},
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
