"""Local dangerous command detection."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SafetyVerdict:
    """A local safety decision for a generated command."""

    action: Literal["allow", "block"]
    reason: str = ""


HARD_BLOCK_PATTERNS: list[tuple[str, str]] = [
    # Blocks recursive forced deletion of the filesystem root.
    (
        r"\brm\s+(?:-[A-Za-z]*r[A-Za-z]*f[A-Za-z]*|-[A-Za-z]*f[A-Za-z]*r[A-Za-z]*)\s+/(?:\s|$)",
        "删除根目录",
    ),
    # Blocks recursive forced deletion of the user's home directory.
    (
        r"\brm\s+(?:-[A-Za-z]*r[A-Za-z]*f[A-Za-z]*|-[A-Za-z]*f[A-Za-z]*r[A-Za-z]*)\s+~(?:/)?(?:\s|$)",
        "删除用户主目录",
    ),
    # Blocks filesystem formatting commands.
    (r"\bmkfs(?:\.[A-Za-z0-9_-]+)?\b", "格式化磁盘分区"),
    # Blocks raw writes to common disk device names.
    (
        r"\bdd\s+.*\bof=/dev/(?:sd[a-z]\d*|nvme\d+n\d+(?:p\d+)?|disk\d+)\b",
        "直接写入磁盘设备",
    ),
    # Blocks shell redirection directly to common disk device names.
    (r">\s*/dev/(?:sd[a-z]\d*|nvme\d+n\d+(?:p\d+)?|disk\d+)\b", "直接覆盖磁盘设备"),
    # Blocks classic shell fork bombs.
    (r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    # Blocks decoding or fetching opaque data and piping it into a shell.
    (
        r"\bbase64\s+(?:-[A-Za-z]*d[A-Za-z]*|--decode)\b.*\|\s*(?:ba|z|fi)?sh\b",
        "远程代码执行管道",
    ),
    # Blocks common remote-download-to-shell execution patterns.
    (r"\b(?:curl|wget)\b.*\|\s*(?:sudo\s+)?(?:ba|z|fi)?sh\b", "远程下载后直接执行"),
    # Blocks recursively making the entire filesystem world-writable.
    (r"\bchmod\s+-R\s+777\s+/(?:\s|$)", "全盘权限放开"),
]


def check_command(command: str) -> SafetyVerdict:
    """Check a shell command against local hard-block safety patterns."""

    normalized = _normalize(command)
    rm_reason = _dangerous_rm_reason(command)
    if rm_reason:
        return SafetyVerdict("block", rm_reason)
    for pattern, reason in HARD_BLOCK_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE | re.DOTALL):
            return SafetyVerdict("block", reason)
    return SafetyVerdict("allow")


def split_command_for_display(command: str) -> list[str]:
    """Split a command into shell-like tokens for diagnostics."""

    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _normalize(command: str) -> str:
    return " ".join(command.strip().split())


def _dangerous_rm_reason(command: str) -> str:
    tokens = split_command_for_display(command)
    control_tokens = {";", "&&", "||", "|"}
    for index, token in enumerate(tokens):
        if token != "rm":
            continue
        recursive = False
        forced = False
        for next_token in tokens[index + 1 :]:
            if next_token in control_tokens:
                break
            if next_token == "-":
                continue
            if next_token == "--":
                continue
            if next_token.startswith("-") and next_token != "-":
                option = next_token.lstrip("-")
                recursive = recursive or "r" in option or "R" in option
                forced = forced or "f" in option
                continue
            target = "/" if next_token == "/" else next_token.rstrip("/")
            if recursive and forced and target in {"/", "~"}:
                return "删除根目录" if target == "/" else "删除用户主目录"
    return ""
