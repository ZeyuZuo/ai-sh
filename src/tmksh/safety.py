"""Local dangerous command detection."""

from __future__ import annotations

import posixpath
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
    return _dangerous_rm_reason_at_depth(command, depth=0)


def _dangerous_rm_reason_at_depth(command: str, *, depth: int) -> str:
    tokens = _split_shell_tokens(command)
    control_tokens = {";", "&&", "||", "|", "&", "(", ")"}
    for index, token in enumerate(tokens):
        if depth < 2 and _shell_name(token) in {"sh", "bash", "zsh", "fish"}:
            payload = _shell_command_payload(tokens, index, control_tokens)
            if payload:
                reason = _dangerous_rm_reason_at_depth(payload, depth=depth + 1)
                if reason:
                    return reason
        if token != "rm":
            continue
        recursive = False
        forced = False
        targets: list[str] = []
        parse_options = True
        for next_token in tokens[index + 1 :]:
            if next_token in control_tokens or _is_redirection_token(next_token):
                break
            if next_token == "-":
                targets.append(next_token)
                continue
            if next_token == "--":
                parse_options = False
                continue
            if parse_options and next_token.startswith("--"):
                recursive = recursive or next_token == "--recursive"
                forced = forced or next_token == "--force"
                continue
            if parse_options and next_token.startswith("-"):
                option = next_token[1:]
                recursive = recursive or "r" in option or "R" in option
                forced = forced or "f" in option
                continue
            targets.append(next_token)
        if recursive and forced:
            for target in targets:
                reason = _dangerous_rm_target_reason(target)
                if reason:
                    return reason
    return ""


def _split_shell_tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(
            command.replace("\n", "\n;\n"),
            posix=True,
            punctuation_chars=";&|()<>",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return command.split()


def _shell_name(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _shell_command_payload(
    tokens: list[str], index: int, control_tokens: set[str]
) -> str:
    for option_index in range(index + 1, len(tokens)):
        option = tokens[option_index]
        if option in control_tokens:
            return ""
        if option == "--command" or (
            option.startswith("-") and not option.startswith("--") and "c" in option[1:]
        ):
            payload_index = option_index + 1
            if (
                payload_index < len(tokens)
                and tokens[payload_index] not in control_tokens
            ):
                return tokens[payload_index]
            return ""
        if not option.startswith("-"):
            return ""
    return ""


def _is_redirection_token(token: str) -> bool:
    return bool(token) and all(character in "<>" for character in token)


def _dangerous_rm_target_reason(target: str) -> str:
    trimmed = target.rstrip("/")
    if trimmed in {"~", "$HOME", "${HOME}"} or target in {
        "~/*",
        "$HOME/*",
        "${HOME}/*",
    }:
        return "删除用户主目录"

    normalized = posixpath.normpath("/" + target.lstrip("/"))
    if target.startswith("/") and normalized == "/":
        return "删除根目录"
    if target in {"/*", "/.??*", "/.[!.]*", "/{*,.*}"}:
        return "删除根目录"
    return ""
