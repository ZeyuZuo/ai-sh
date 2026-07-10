"""OpenAI-compatible LLM client and prompt handling."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

from ai_sh.config import Config, require_api_key
from ai_sh.exceptions import ApiError

RiskLevel = Literal["safe", "caution", "danger"]
ResultKind = Literal["command", "answer", "clarification", "blocked", "error"]


class ChatMessage(TypedDict):
    """A chat message sent to an OpenAI-compatible API."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class AssistantResult:
    """A normalized command, answer, clarification, block, or error result."""

    kind: ResultKind = "command"
    command: str = ""
    answer: str = ""
    explanation: str = ""
    risk_level: RiskLevel = "caution"
    risk_reason: str = ""
    clarification: str = ""
    error: str = ""


SYSTEM_PROMPT = """你是 ai-sh，一个谨慎的命令行助手。
你根据用户意图和环境上下文生成一条适合当前 shell 的命令。

必须只返回 JSON，不要返回 Markdown，不要使用代码块。
JSON schema:
{
  "kind": "command | clarification",
  "command": "string，若需要澄清则为空字符串",
  "answer": "string，命令生成模式下始终为空",
  "explanation": "string，解释命令做什么",
  "risk_level": "safe | caution | danger",
  "risk_reason": "string，risk_level 为 caution 或 danger 时必须说明原因",
  "clarification": "string，只有意图模糊需要追问时填写",
  "error": "string，始终为空"
}

规则：
- 生成命令时 kind 为 command；需要追问时 kind 为 clarification。
- 当用户意图不清楚、缺少必要路径或范围时，填写 clarification，并让 command 为空。
- 只生成一条命令，不生成多步骤脚本。
- 不要编造当前环境中不存在的工具。
- 删除、覆盖、递归修改、大量移动文件、权限修改、网络下载并执行等操作至少标记为 caution。
- 明显破坏系统或不可逆高风险命令标记为 danger。
- 响应语言应匹配用户语言，除非上下文指定 language。
"""


def build_messages(
    user_input: str,
    env_context: dict[str, object],
    *,
    stdin_context: str = "",
    current_command: str = "",
    conversation: list[ChatMessage] | None = None,
    language: str = "zh",
) -> list[ChatMessage]:
    """Build chat messages for command generation."""

    context_json = json.dumps(env_context, ensure_ascii=False, indent=2)
    user_parts = [
        f"响应语言: {language}",
        "环境上下文:",
        context_json,
    ]
    if stdin_context:
        user_parts.extend(
            [
                "stdin 上下文，可能是用户希望分析或处理的内容:",
                _truncate(stdin_context, 8000),
            ]
        )
    if current_command:
        user_parts.extend(
            [
                "当前 Shell 输入缓冲区中的命令，用户希望基于它修改:",
                _truncate(current_command, 8000),
            ]
        )
    user_parts.extend(["用户意图:", user_input])

    messages: list[ChatMessage] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if conversation:
        messages.extend(conversation[-20:])
    messages.append({"role": "user", "content": "\n".join(user_parts)})
    return messages


def generate_command(config: Config, messages: list[ChatMessage]) -> AssistantResult:
    """Call the configured OpenAI-compatible API and parse a command result."""

    api_key = require_api_key(config)
    client = OpenAI(api_key=api_key, base_url=config.api.base_url, timeout=20.0)

    try:
        response = client.chat.completions.create(
            model=config.api.model,
            messages=messages,  # type: ignore[arg-type]
            response_format={"type": "json_object"},
            temperature=0.2,
        )
    except TypeError:
        response = _create_without_json_mode(client, config, messages)
    except (APITimeoutError, APIConnectionError) as exc:
        raise ApiError("连接 AI 服务超时或失败，请检查网络后重试。") from exc
    except RateLimitError as exc:
        raise ApiError("AI 服务返回限流，请稍后重试。") from exc
    except APIError as exc:
        if _looks_like_json_mode_rejection(exc):
            response = _create_without_json_mode(client, config, messages)
        else:
            raise ApiError(f"AI 服务调用失败：{_safe_api_message(exc)}") from exc

    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise ApiError("AI 服务返回了无法识别的响应结构。") from exc
    if not content:
        raise ApiError("AI 服务返回了空响应。")
    return parse_command_result(content)


def parse_command_result(content: str) -> AssistantResult:
    """Parse the model's JSON response into an AssistantResult."""

    data = _loads_json(content)
    command = _string(data.get("command"))
    answer = _string(data.get("answer"))
    explanation = _string(data.get("explanation"))
    risk_level = _risk_level(data.get("risk_level"))
    risk_reason = _string(data.get("risk_reason"))
    clarification = _string(data.get("clarification"))
    error = _string(data.get("error"))
    kind = _result_kind(data.get("kind"), command, answer, clarification, error)

    if kind == "command" and not command:
        raise ApiError("AI 响应缺少 command 字段。")
    if kind == "command" and not explanation:
        raise ApiError("AI 响应缺少 explanation 字段。")
    if kind == "answer" and not answer:
        raise ApiError("AI 响应缺少 answer 字段。")
    if kind == "clarification" and not clarification:
        raise ApiError("AI 响应缺少 clarification 字段。")
    if kind == "error" and not error:
        raise ApiError("AI 响应缺少 error 字段。")
    if kind == "command" and risk_level in {"caution", "danger"} and not risk_reason:
        risk_reason = "AI 标记该命令存在风险。"

    return AssistantResult(
        kind=kind,
        command=command,
        answer=answer,
        explanation=explanation,
        risk_level=risk_level,
        risk_reason=risk_reason,
        clarification=clarification,
        error=error,
    )


def result_to_assistant_message(result: AssistantResult) -> ChatMessage:
    """Serialize a command result back into conversation history."""

    return {
        "role": "assistant",
        "content": json.dumps(
            {
                "kind": result.kind,
                "command": result.command,
                "answer": result.answer,
                "explanation": result.explanation,
                "risk_level": result.risk_level,
                "risk_reason": result.risk_reason,
                "clarification": result.clarification,
                "error": result.error,
            },
            ensure_ascii=False,
        ),
    }


def _create_without_json_mode(
    client: OpenAI, config: Config, messages: list[ChatMessage]
) -> Any:
    try:
        return client.chat.completions.create(
            model=config.api.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=0.2,
        )
    except (APITimeoutError, APIConnectionError) as exc:
        raise ApiError("连接 AI 服务超时或失败，请检查网络后重试。") from exc
    except RateLimitError as exc:
        raise ApiError("AI 服务返回限流，请稍后重试。") from exc
    except APIError as exc:
        raise ApiError(f"AI 服务调用失败：{_safe_api_message(exc)}") from exc


def _loads_json(content: str) -> dict[str, object]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise ApiError("AI 响应不是有效 JSON。") from None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ApiError("AI 响应中的 JSON 无法解析。") from exc
    if not isinstance(data, dict):
        raise ApiError("AI 响应 JSON 顶层必须是对象。")
    return data


def _risk_level(value: object) -> RiskLevel:
    if value in {"safe", "caution", "danger"}:
        return value  # type: ignore[return-value]
    return "caution"


def _result_kind(
    value: object,
    command: str,
    answer: str,
    clarification: str,
    error: str,
) -> ResultKind:
    if value in {"command", "answer", "clarification", "blocked", "error"}:
        return value  # type: ignore[return-value]
    if command:
        return "command"
    if answer:
        return "answer"
    if clarification:
        return "clarification"
    if error:
        return "error"
    raise ApiError("AI 响应缺少可识别的结果类型。")


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


def _safe_api_message(exc: APIError) -> str:
    message = str(exc)
    return re.sub(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[redacted]", message)


def _looks_like_json_mode_rejection(exc: APIError) -> bool:
    message = str(exc).lower()
    return "response_format" in message or "json_object" in message
