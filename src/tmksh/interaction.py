"""User directives and shell-captured command state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DirectiveKind = Literal["natural", "fix"]


@dataclass(frozen=True)
class UserDirective:
    """A locally parsed widget request."""

    kind: DirectiveKind
    argument: str


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
    parts = stripped.split(maxsplit=1)
    name = parts[0]
    if name.lower() == "/fix":
        return UserDirective(
            kind="fix", argument=parts[1].strip() if len(parts) > 1 else ""
        )
    return UserDirective(kind="natural", argument=stripped)
