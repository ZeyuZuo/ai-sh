import json
from io import BytesIO

import pytest
from click.testing import CliRunner

from tmksh.cli import tmksh
from tmksh.config import ApiConfig, BehaviorConfig, Config
from tmksh.exceptions import ApiError, ConfigError
from tmksh.llm import AssistantResult
from tmksh.protocol import (
    MAX_BUFFER_CHARS,
    MAX_PROTOCOL_INPUT_BYTES,
    MAX_REQUEST_CHARS,
    PROTOCOL_VERSION,
    ProtocolExitCode,
    ProtocolInputError,
    read_nul_protocol_request,
    read_protocol_request,
)
from tmksh.suggestion import Suggestion


def test_suggest_protocol_round_trips_special_characters(monkeypatch, tmp_path) -> None:
    request = '查找 "a|b"\n并保留 $HOME'
    buffer = "printf '%s\\n' \"雪 | $HOME\"\n"
    command = "rg 'a\\|b' \"$HOME/雪\" | head -n 5"
    captured: dict[str, str] = {}
    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))

    def fake_create(config, received_request, *, current_command="", **kwargs):
        captured["request"] = received_request
        captured["buffer"] = current_command
        return Suggestion(
            result=AssistantResult(
                command=command,
                explanation="查找匹配内容。",
                risk_level="safe",
            ),
            environment={"cwd": str(tmp_path)},
        )

    monkeypatch.setattr("tmksh.cli.create_suggestion", fake_create)

    invocation = _invoke_suggest(request=request, buffer=buffer)

    assert invocation.exit_code == ProtocolExitCode.SUCCESS
    assert invocation.stderr == ""
    assert captured == {"request": request, "buffer": buffer}
    response = json.loads(invocation.stdout)
    assert response == {
        "protocol_version": PROTOCOL_VERSION,
        "kind": "command",
        "command": command,
        "answer": "",
        "explanation": "查找匹配内容。",
        "risk_level": "safe",
        "risk_reason": "",
        "clarification": "",
        "error": "",
    }


def test_tmksh_json_uses_protocol_output_without_executing(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "tmksh.cli.create_suggestion",
        lambda *args, **kwargs: Suggestion(
            AssistantResult(
                command="git status --short",
                explanation="查看状态。",
                risk_level="safe",
            ),
            {"cwd": str(tmp_path)},
        ),
    )
    invocation = CliRunner().invoke(tmksh, ["--json", "查看", "状态"])

    assert invocation.exit_code == ProtocolExitCode.SUCCESS
    assert invocation.stderr == ""
    response = json.loads(invocation.stdout)
    assert response["kind"] == "command"
    assert response["command"] == "git status --short"


def test_tmksh_json_applies_request_limit_before_loading_config(monkeypatch) -> None:
    monkeypatch.setattr(
        "tmksh.cli.load_config",
        lambda: pytest.fail("invalid request must be rejected before config loading"),
    )

    invocation = CliRunner().invoke(
        tmksh,
        ["--json", "x" * (MAX_REQUEST_CHARS + 1)],
    )

    assert invocation.exit_code == ProtocolExitCode.INVALID_REQUEST
    response = json.loads(invocation.stdout)
    assert response["kind"] == "error"
    assert "request" in response["error"]


@pytest.mark.parametrize(
    ("assistant_result", "expected_exit"),
    [
        (
            AssistantResult(kind="clarification", clarification="请提供目录。"),
            ProtocolExitCode.CLARIFICATION,
        ),
        (
            AssistantResult(
                kind="blocked",
                risk_level="danger",
                risk_reason="删除根目录",
            ),
            ProtocolExitCode.BLOCKED,
        ),
    ],
)
def test_suggest_protocol_uses_result_exit_codes(
    monkeypatch, tmp_path, assistant_result, expected_exit
) -> None:
    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "tmksh.cli.create_suggestion",
        lambda *args, **kwargs: Suggestion(assistant_result, {"cwd": str(tmp_path)}),
    )

    invocation = _invoke_suggest()

    assert invocation.exit_code == expected_exit
    response = json.loads(invocation.stdout)
    assert response["kind"] == assistant_result.kind
    assert invocation.stderr == ""


def test_suggest_protocol_applies_local_safety_before_response(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "tmksh.suggestion.collect_context",
        lambda: {"cwd": str(tmp_path)},
    )
    monkeypatch.setattr(
        "tmksh.suggestion.generate_command",
        lambda config, messages: AssistantResult(
            command="rm -rf /",
            explanation="incorrectly classified",
            risk_level="safe",
        ),
    )

    invocation = _invoke_suggest()

    assert invocation.exit_code == ProtocolExitCode.BLOCKED
    response = json.loads(invocation.stdout)
    assert response["kind"] == "blocked"
    assert response["command"] == ""
    assert response["risk_reason"] == "删除根目录"


def test_suggest_protocol_returns_config_error_json(monkeypatch) -> None:
    monkeypatch.setattr(
        "tmksh.cli.load_config",
        lambda: (_ for _ in ()).throw(ConfigError("缺少配置。")),
    )

    invocation = _invoke_suggest()

    assert invocation.exit_code == ProtocolExitCode.CONFIG_ERROR
    assert json.loads(invocation.stdout)["error"] == "缺少配置。"
    assert invocation.stderr == ""


def test_suggest_protocol_redacts_api_key_from_api_errors(
    monkeypatch, tmp_path
) -> None:
    secret = "super-secret-api-key"
    monkeypatch.setattr(
        "tmksh.cli.load_config", lambda: _config(tmp_path, api_key=secret)
    )
    monkeypatch.setattr(
        "tmksh.cli.create_suggestion",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ApiError(f"Bearer {secret}; api_key={secret}")
        ),
    )

    invocation = _invoke_suggest()

    assert invocation.exit_code == ProtocolExitCode.API_ERROR
    assert secret not in invocation.stdout
    assert secret not in invocation.stderr
    response = json.loads(invocation.stdout)
    assert response["kind"] == "error"
    assert "[redacted]" in response["error"]


def test_suggest_protocol_hides_unexpected_exception_details(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "tmksh.cli.create_suggestion",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("sensitive implementation detail")
        ),
    )

    invocation = _invoke_suggest()

    assert invocation.exit_code == ProtocolExitCode.INTERNAL_ERROR
    response = json.loads(invocation.stdout)
    assert response["error"] == "tmksh 内部错误。"
    assert "sensitive" not in invocation.stdout


def test_suggest_protocol_returns_json_when_interrupted(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        "tmksh.cli.create_suggestion",
        lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    invocation = _invoke_suggest()

    assert invocation.exit_code == ProtocolExitCode.INTERRUPTED
    response = json.loads(invocation.stdout)
    assert response["kind"] == "error"
    assert response["error"] == "请求已取消。"


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        json.dumps({"protocol_version": 2, "request": "test"}),
        json.dumps({"protocol_version": 1, "request": ""}),
        json.dumps({"protocol_version": 1, "request": "test", "buffer": 1}),
        json.dumps({"protocol_version": 1, "request": "x" * (MAX_REQUEST_CHARS + 1)}),
        json.dumps(
            {
                "protocol_version": 1,
                "request": "test",
                "buffer": "x" * (MAX_BUFFER_CHARS + 1),
            }
        ),
    ],
)
def test_suggest_protocol_rejects_invalid_requests_as_json(payload: str) -> None:
    invocation = CliRunner().invoke(tmksh, ["suggest"], input=payload)

    assert invocation.exit_code == ProtocolExitCode.INVALID_REQUEST
    response = json.loads(invocation.stdout)
    assert response["kind"] == "error"
    assert response["error"]
    assert invocation.stderr == ""


def test_protocol_input_has_total_byte_limit() -> None:
    with pytest.raises(ProtocolInputError, match="字节限制"):
        read_protocol_request(BytesIO(b"x" * (MAX_PROTOCOL_INPUT_BYTES + 1)))


def test_suggest_protocol_reports_total_byte_limit_as_json() -> None:
    invocation = CliRunner().invoke(
        tmksh,
        ["suggest"],
        input="x" * (MAX_PROTOCOL_INPUT_BYTES + 1),
    )

    assert invocation.exit_code == ProtocolExitCode.INVALID_REQUEST
    response = json.loads(invocation.stdout)
    assert "字节限制" in response["error"]


def test_protocol_input_requires_utf8() -> None:
    with pytest.raises(ProtocolInputError, match="UTF-8"):
        read_protocol_request(BytesIO(b"\xff"))


def test_nul_protocol_preserves_request_and_buffer() -> None:
    request = "按时间排序\n保留空格"
    buffer = "find src -type f | head"

    parsed = read_nul_protocol_request(
        BytesIO(request.encode() + b"\0" + buffer.encode())
    )

    assert parsed.request == request
    assert parsed.buffer == buffer


def test_nul_protocol_requires_exactly_two_fields() -> None:
    with pytest.raises(ProtocolInputError, match="两个字段"):
        read_nul_protocol_request(BytesIO(b"request-only"))


def test_suggest_cli_accepts_nul_transport(monkeypatch, tmp_path) -> None:
    captured: dict[str, str] = {}
    monkeypatch.setattr("tmksh.cli.load_config", lambda: _config(tmp_path))

    def fake_create(config, request, *, current_command="", **kwargs):
        captured.update(request=request, buffer=current_command)
        return Suggestion(
            AssistantResult(
                command="find src -type f | sort",
                explanation="sort files",
                risk_level="safe",
            ),
            {"cwd": str(tmp_path)},
        )

    monkeypatch.setattr("tmksh.cli.create_suggestion", fake_create)

    invocation = CliRunner().invoke(
        tmksh,
        ["suggest", "--input-format", "nul"],
        input="按时间排序\0find src -type f",
    )

    assert invocation.exit_code == ProtocolExitCode.SUCCESS
    assert captured == {"request": "按时间排序", "buffer": "find src -type f"}
    assert json.loads(invocation.stdout)["kind"] == "command"


def _invoke_suggest(*, request: str = "列出文件", buffer: str = ""):
    payload = json.dumps(
        {
            "protocol_version": PROTOCOL_VERSION,
            "request": request,
            "buffer": buffer,
        },
        ensure_ascii=False,
    )
    return CliRunner().invoke(tmksh, ["suggest"], input=payload)


def _config(tmp_path, *, api_key: str = "test-key") -> Config:
    return Config(
        api=ApiConfig(api_key=api_key),
        behavior=BehaviorConfig(),
        path=tmp_path / "config.toml",
    )
