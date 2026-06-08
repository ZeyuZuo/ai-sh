"""OpenAI-compatible LLM client and prompt handling."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

from ai_sh.config import Config, require_api_key
from ai_sh.exceptions import ApiError

RiskLevel = Literal["safe", "caution", "danger"]


class ChatMessage(TypedDict):
    """A chat message sent to an OpenAI-compatible API."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class CommandResult:
    """A generated shell command and its safety metadata."""

    command: str
    explanation: str
    risk_level: RiskLevel
    risk_reason: str = ""
    alternatives: list[str] = field(default_factory=list)
    clarification: str = ""


SYSTEM_PROMPT = """你是 ai-sh，一个谨慎的命令行助手。
你根据用户意图和环境上下文生成一条适合当前 shell 的命令。

必须只返回 JSON，不要返回 Markdown，不要使用代码块。
JSON schema:
{
  "command": "string，若需要澄清则为空字符串",
  "explanation": "string，解释命令做什么",
  "risk_level": "safe | caution | danger",
  "risk_reason": "string，risk_level 为 caution 或 danger 时必须说明原因",
  "alternatives": ["string"],
  "clarification": "string，只有意图模糊需要追问时填写"
}

规则：
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
    user_parts.extend(["用户意图:", user_input])

    messages: list[ChatMessage] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if conversation:
        messages.extend(conversation[-20:])
    messages.append({"role": "user", "content": "\n".join(user_parts)})
    return messages


def generate_command(config: Config, messages: list[ChatMessage]) -> CommandResult:
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
        raise ApiError(f"AI 服务调用失败：{_safe_api_message(exc)}") from exc

    content = response.choices[0].message.content
    if not content:
        raise ApiError("AI 服务返回了空响应。")
    return parse_command_result(content)


def parse_command_result(content: str) -> CommandResult:
    """Parse the model's JSON response into a CommandResult."""

    data = _loads_json(content)
    command = _string(data.get("command"))
    explanation = _string(data.get("explanation"))
    risk_level = _risk_level(data.get("risk_level"))
    risk_reason = _string(data.get("risk_reason"))
    alternatives = _string_list(data.get("alternatives"))
    clarification = _string(data.get("clarification"))

    if not command and not clarification:
        raise ApiError("AI 响应缺少 command 或 clarification 字段。")
    if command and not explanation:
        raise ApiError("AI 响应缺少 explanation 字段。")
    if risk_level in {"caution", "danger"} and not risk_reason:
        risk_reason = "AI 标记该命令存在风险。"

    return CommandResult(
        command=command,
        explanation=explanation,
        risk_level=risk_level,
        risk_reason=risk_reason,
        alternatives=alternatives,
        clarification=clarification,
    )


def result_to_assistant_message(result: CommandResult) -> ChatMessage:
    """Serialize a command result back into conversation history."""

    return {
        "role": "assistant",
        "content": json.dumps(
            {
                "command": result.command,
                "explanation": result.explanation,
                "risk_level": result.risk_level,
                "risk_reason": result.risk_reason,
                "alternatives": result.alternatives,
                "clarification": result.clarification,
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


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


def _safe_api_message(exc: APIError) -> str:
    message = str(exc)
    return re.sub(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[redacted]", message)
