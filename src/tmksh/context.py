"""Collect local environment context for command generation."""

from __future__ import annotations

import getpass
import os
import platform
import shutil
from pathlib import Path

KEY_TOOLS = [
    "git",
    "docker",
    "kubectl",
    "python3",
    "python",
    "uv",
    "rg",
    "fd",
    "jq",
    "aws",
    "gcloud",
    "az",
]


def collect_context(recent_commands: list[str] | None = None) -> dict[str, object]:
    """Collect shell, OS, user, cwd, tools, and recent command context."""

    return {
        "cwd": str(Path.cwd()),
        "shell": detect_shell(),
        "os": detect_os(),
        "username": getpass.getuser(),
        "tools": detect_tools(),
        "recent_commands": recent_commands or [],
    }


def detect_shell() -> str:
    """Detect the user's current shell from environment variables."""

    shell = os.getenv("SHELL", "")
    name = Path(shell).name if shell else ""
    return name or "unknown"


def detect_os() -> dict[str, str]:
    """Detect platform and Linux distribution details when available."""

    info = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
    }
    os_release = Path("/etc/os-release")
    if os_release.exists():
        for line in os_release.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines():
            if line.startswith("PRETTY_NAME="):
                info["distribution"] = line.split("=", 1)[1].strip('"')
                break
    return info


def detect_tools(tools: list[str] | None = None) -> dict[str, bool]:
    """Return whether important command-line tools are available on PATH."""

    candidates = tools or KEY_TOOLS
    return {tool: shutil.which(tool) is not None for tool in candidates}
