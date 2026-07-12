"""User directives and shell-captured command state."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Literal

DirectiveKind = Literal[
    "natural",
    "fix",
    "explain",
    "check",
    "new",
    "ask",
    "help",
    "unknown",
]

HELP_TEXT = """/fix [补充信息]       修复最近失败的命令
/explain [关注点]     解释当前或上一条命令
/check [检查重点]     检查正确性、风险和兼容性
/new <任务>           忽略当前 buffer 生成新命令
/ask <问题>           回答问题，不修改 buffer
/help                 显示本帮助"""

_DIRECTIVE_KINDS: dict[str, DirectiveKind] = {
    "/fix": "fix",
    "/explain": "explain",
    "/check": "check",
    "/new": "new",
    "/ask": "ask",
    "/help": "help",
}
SUPPORTED_DIRECTIVES = tuple(_DIRECTIVE_KINDS)
_DIRECTIVE_NAME = re.compile(r"/[A-Za-z][A-Za-z0-9_-]*")


@dataclass(frozen=True)
class UserDirective:
    """A locally parsed widget request."""

    kind: DirectiveKind
    argument: str
    name: str = ""


@dataclass(frozen=True)
class FailedCommandContext:
    """The most recent failed command captured by the active shell."""

    command: str
    exit_code: int
    cwd: str
    shell: str


def parse_user_directive(value: str) -> UserDirective:
    """Recognize supported slash directives without involving the model."""

    stripped = value.strip()
    if not stripped:
        return UserDirective(kind="natural", argument="")

    parts = stripped.split(maxsplit=1)
    name = parts[0]
    normalized_name = name.lower()
    kind = _DIRECTIVE_KINDS.get(normalized_name)
    if kind is not None:
        return UserDirective(
            kind=kind,
            argument=parts[1].strip() if len(parts) > 1 else "",
        )

    if _DIRECTIVE_NAME.fullmatch(name):
        return UserDirective(kind="unknown", argument="", name=name)

    return UserDirective(kind="natural", argument=stripped)


def unknown_directive_message(name: str) -> str:
    """Describe an unknown directive and suggest the closest supported names."""

    matches = get_close_matches(name.lower(), SUPPORTED_DIRECTIVES, n=2, cutoff=0.5)
    lines = [f"未知指令：{name}"]
    if matches:
        lines.append(f"你是否想使用：{'、'.join(matches)}")
    lines.extend(("", HELP_TEXT))
    return "\n".join(lines)
