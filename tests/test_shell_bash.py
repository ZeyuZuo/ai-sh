import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from ai_sh.cli import ai_sh
from ai_sh.shell import render_bash_init


def test_bash_init_command_outputs_loadable_script() -> None:
    invocation = CliRunner().invoke(ai_sh, ["init", "bash"])

    assert invocation.exit_code == 0
    assert "__ai_sh_widget" in invocation.stdout
    assert "READLINE_LINE" in invocation.stdout
    assert "bind -x" in invocation.stdout
    assert "suggest --input-format nul" in invocation.stdout

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
        command_path="/opt/ai sh/bin/ai-sh",
        python_path="/opt/python/bin/python",
    )

    assert r'"\C-x\C-a":__ai_sh_widget' in script
    assert "'/opt/ai sh/bin/ai-sh'" in script


def test_bash_widget_replaces_buffer_without_executing(tmp_path) -> None:
    completed = _run_widget(
        tmp_path,
        user_input="按修改时间排序\n",
        original_line="find src -type f",
    )

    assert completed.returncode == 0, completed.stderr
    assert "safe · generated safely" in completed.stdout
    assert _line_from_output(completed.stdout) == "find src -type f | sort -nr"


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
    )
    cancelled = _run_widget(
        tmp_path,
        user_input="\n",
        original_line="keep --this",
    )

    assert "删除根目录" in blocked.stdout
    assert _line_from_output(blocked.stdout) == "keep --this"
    assert _line_from_output(cancelled.stdout) == "keep --this"


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
READLINE_POINT=${#READLINE_LINE}
__ai_sh_widget
printf '\n__AI_SH_LINE__=%s\n' "$READLINE_LINE"
printf '__AI_SH_POINT__=%s\n' "$READLINE_POINT"
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
        ],
        input=user_input,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_fake_backend(tmp_path: Path) -> Path:
    path = tmp_path / "fake-ai-sh"
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
    marker = "__AI_SH_LINE__="
    return output.split(marker, 1)[1].splitlines()[0]
