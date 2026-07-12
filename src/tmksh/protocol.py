"""Versioned machine protocol for shell suggestion clients."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from enum import IntEnum
from typing import BinaryIO

from tmksh.interaction import FailedCommandContext
from tmksh.llm import AssistantResult, ResultKind, RiskLevel

PROTOCOL_VERSION = 1
MAX_PROTOCOL_INPUT_BYTES = 128 * 1024
MAX_REQUEST_CHARS = 4096
MAX_BUFFER_CHARS = 32 * 1024
MAX_STDIN_CONTEXT_CHARS = 64 * 1024
MAX_FAILED_COMMAND_CHARS = 32 * 1024
MAX_FAILED_CWD_CHARS = 4096
MAX_SHELL_NAME_CHARS = 64


class ProtocolExitCode(IntEnum):
    """Stable process exit codes for the suggestion protocol."""

    SUCCESS = 0
    INVALID_REQUEST = 2
    CONFIG_ERROR = 20
    API_ERROR = 21
    CLARIFICATION = 30
    BLOCKED = 31
    MISSING_CONTEXT = 32
    INTERNAL_ERROR = 70
    INTERRUPTED = 130


class ProtocolInputError(ValueError):
    """Raised when a machine request does not match protocol version 1."""


@dataclass(frozen=True)
class ProtocolRequest:
    """A shell widget request read from stdin."""

    protocol_version: int
    request: str
    buffer: str = ""
    failed_command: FailedCommandContext | None = None


@dataclass(frozen=True)
class ProtocolResponse:
    """A stable JSON response written to stdout."""

    protocol_version: int = PROTOCOL_VERSION
    kind: ResultKind = "error"
    command: str = ""
    answer: str = ""
    explanation: str = ""
    risk_level: RiskLevel = "caution"
    risk_reason: str = ""
    clarification: str = ""
    error: str = ""

    @classmethod
    def from_result(cls, result: AssistantResult) -> ProtocolResponse:
        """Create a protocol response from a normalized assistant result."""

        return cls(
            kind=result.kind,
            command=result.command,
            answer=result.answer,
            explanation=result.explanation,
            risk_level=result.risk_level,
            risk_reason=result.risk_reason,
            clarification=result.clarification,
            error=result.error,
        )

    @classmethod
    def error_response(cls, message: str) -> ProtocolResponse:
        """Create a machine-readable error response."""

        return cls(kind="error", error=message)

    def to_json(self) -> str:
        """Serialize the response as one compact JSON object."""

        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))


def read_protocol_request(stream: BinaryIO) -> ProtocolRequest:
    """Read and validate one size-bounded protocol request from a binary stream."""

    payload = stream.read(MAX_PROTOCOL_INPUT_BYTES + 1)
    if len(payload) > MAX_PROTOCOL_INPUT_BYTES:
        raise ProtocolInputError(f"请求数据超过 {MAX_PROTOCOL_INPUT_BYTES} 字节限制。")
    if not payload:
        raise ProtocolInputError("stdin 中缺少协议请求。")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolInputError("协议请求必须使用 UTF-8 编码。") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolInputError("协议请求不是有效 JSON。") from exc
    if not isinstance(data, dict):
        raise ProtocolInputError("协议请求 JSON 顶层必须是对象。")

    version = data.get("protocol_version")
    if version != PROTOCOL_VERSION:
        raise ProtocolInputError(
            f"不支持 protocol_version={version!r}，当前仅支持 {PROTOCOL_VERSION}。"
        )

    return validate_protocol_fields(
        data.get("request"),
        data.get("buffer", ""),
        data.get("failed_command"),
    )


def read_nul_protocol_request(stream: BinaryIO) -> ProtocolRequest:
    """Read a shell-safe request with optional failed-command fields."""

    payload = stream.read(MAX_PROTOCOL_INPUT_BYTES + 1)
    if len(payload) > MAX_PROTOCOL_INPUT_BYTES:
        raise ProtocolInputError(f"请求数据超过 {MAX_PROTOCOL_INPUT_BYTES} 字节限制。")
    parts = payload.split(b"\0")
    if len(parts) not in {2, 6}:
        raise ProtocolInputError("NUL 请求必须包含 2 个或 6 个字段。")
    try:
        decoded = [part.decode("utf-8") for part in parts]
    except UnicodeDecodeError as exc:
        raise ProtocolInputError("协议请求必须使用 UTF-8 编码。") from exc
    request, buffer = decoded[:2]
    failed_command: object = None
    if len(decoded) == 6:
        command, exit_code, cwd, shell = decoded[2:]
        if any((command, exit_code, cwd, shell)):
            failed_command = {
                "command": command,
                "exit_code": exit_code,
                "cwd": cwd,
                "shell": shell,
            }
    return validate_protocol_fields(request, buffer, failed_command)


def validate_protocol_fields(
    request: object,
    buffer: object,
    failed_command: object = None,
) -> ProtocolRequest:
    """Validate fields shared by machine entry points."""

    if not isinstance(request, str) or not request.strip():
        raise ProtocolInputError("request 必须是非空字符串。")
    if not isinstance(buffer, str):
        raise ProtocolInputError("buffer 必须是字符串。")
    if len(request) > MAX_REQUEST_CHARS:
        raise ProtocolInputError(f"request 超过 {MAX_REQUEST_CHARS} 字符限制。")
    if len(buffer) > MAX_BUFFER_CHARS:
        raise ProtocolInputError(f"buffer 超过 {MAX_BUFFER_CHARS} 字符限制。")

    return ProtocolRequest(
        protocol_version=PROTOCOL_VERSION,
        request=request,
        buffer=buffer,
        failed_command=_validate_failed_command(failed_command),
    )


def _validate_failed_command(value: object) -> FailedCommandContext | None:
    if value is None:
        return None
    command_value: object
    exit_code_value: object
    cwd_value: object
    shell_value: object
    if isinstance(value, FailedCommandContext):
        command_value = value.command
        exit_code_value = value.exit_code
        cwd_value = value.cwd
        shell_value = value.shell
    elif isinstance(value, dict):
        command_value = value.get("command")
        exit_code_value = value.get("exit_code")
        cwd_value = value.get("cwd")
        shell_value = value.get("shell")
    else:
        raise ProtocolInputError("failed_command 必须是对象或 null。")

    if isinstance(exit_code_value, str):
        try:
            exit_code_value = int(exit_code_value)
        except ValueError:
            raise ProtocolInputError("failed_command.exit_code 必须是整数。") from None
    if not isinstance(command_value, str) or not command_value.strip():
        raise ProtocolInputError("failed_command.command 必须是非空字符串。")
    if (
        not isinstance(exit_code_value, int)
        or isinstance(exit_code_value, bool)
        or exit_code_value <= 0
    ):
        raise ProtocolInputError("failed_command.exit_code 必须是正整数。")
    if not isinstance(cwd_value, str) or not cwd_value:
        raise ProtocolInputError("failed_command.cwd 必须是非空字符串。")
    if not isinstance(shell_value, str) or not shell_value:
        raise ProtocolInputError("failed_command.shell 必须是非空字符串。")
    if len(command_value) > MAX_FAILED_COMMAND_CHARS:
        raise ProtocolInputError(
            f"failed_command.command 超过 {MAX_FAILED_COMMAND_CHARS} 字符限制。"
        )
    if len(cwd_value) > MAX_FAILED_CWD_CHARS:
        raise ProtocolInputError(
            f"failed_command.cwd 超过 {MAX_FAILED_CWD_CHARS} 字符限制。"
        )
    if len(shell_value) > MAX_SHELL_NAME_CHARS:
        raise ProtocolInputError(
            f"failed_command.shell 超过 {MAX_SHELL_NAME_CHARS} 字符限制。"
        )
    return FailedCommandContext(
        command=command_value,
        exit_code=exit_code_value,
        cwd=cwd_value,
        shell=shell_value,
    )


def exit_code_for_result(result: AssistantResult) -> ProtocolExitCode:
    """Map a normalized result kind to its stable process exit code."""

    if result.kind in {"command", "answer"}:
        return ProtocolExitCode.SUCCESS
    if result.kind == "clarification":
        return ProtocolExitCode.CLARIFICATION
    if result.kind == "blocked":
        return ProtocolExitCode.BLOCKED
    return ProtocolExitCode.INTERNAL_ERROR


def redact_sensitive(message: str, *, secrets: tuple[str, ...] = ()) -> str:
    """Redact configured secrets and common authorization values from errors."""

    redacted = message
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    redacted = re.sub(
        r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+",
        r"\1[redacted]",
        redacted,
    )
    redacted = re.sub(
        r"""(?i)((?:api[_-]?key|credential|access[_-]?token|secret)["'\s:=]+)"""
        r"""[^\s,"'}]+""",
        r"\1[redacted]",
        redacted,
    )
    return redacted
