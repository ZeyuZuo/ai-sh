"""Execute confirmed shell commands with bounded runtime."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from ai_sh.exceptions import ExecutionError


@dataclass(frozen=True)
class ExecutionResult:
    """Captured process result for a shell command."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


def execute_command(command: str, *, timeout: int = 30) -> ExecutionResult:
    """Execute a user-confirmed command and capture its output."""

    try:
        # shell=True is required because generated commands may use pipes,
        # redirection, globs, and shell builtins that subprocess argv cannot express.
        completed = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return ExecutionResult(
            command=command,
            exit_code=124,
            stdout=_timeout_text(exc.stdout),
            stderr=_timeout_text(exc.stderr) or f"命令执行超过 {timeout} 秒，已终止。",
            timed_out=True,
        )
    except OSError as exc:
        raise ExecutionError(f"无法执行命令：{exc}") from exc

    return ExecutionResult(
        command=command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def summarize_execution(result: ExecutionResult, *, limit: int = 500) -> str:
    """Summarize command output for conversation history."""

    parts = [f"exit_code={result.exit_code}"]
    if result.timed_out:
        parts.append("timed_out=true")
    if result.stdout:
        parts.append("stdout:\n" + _truncate(result.stdout, limit))
    if result.stderr:
        parts.append("stderr:\n" + _truncate(result.stderr, limit))
    return "\n".join(parts)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


def _timeout_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""
