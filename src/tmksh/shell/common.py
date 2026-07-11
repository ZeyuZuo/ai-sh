"""Shared shell widget rendering helpers."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def current_command_path() -> str:
    """Return the executable path embedded in generated shell integrations."""

    resolved = shutil.which(sys.argv[0])
    if resolved:
        return str(Path(resolved).resolve())
    return sys.argv[0] or "tmksh"


JSON_FIELD_PROGRAM = """
import json
import sys

data = json.load(sys.stdin)
field = sys.argv[1]
if field == "message":
    kind = data.get("kind", "error")
    if kind == "command":
        risk = data.get("risk_level", "")
        detail = data.get("risk_reason") if risk == "caution" else data.get("explanation")
        value = f"{risk} · {detail}" if detail else risk
    else:
        value = (
            data.get("error")
            or data.get("clarification")
            or data.get("risk_reason")
            or data.get("explanation")
            or "tmksh did not return a usable result."
        )
else:
    value = data.get(field, "")
sys.stdout.write(value if isinstance(value, str) else "")
""".strip()
