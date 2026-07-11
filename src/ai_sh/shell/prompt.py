"""TTY prompt used by shell widgets without nesting the parent line editor."""

from __future__ import annotations

import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_input
from prompt_toolkit.output import create_output


def prompt_from_tty(label: str) -> str:
    """Read one editable line from /dev/tty, falling back to stdin in tests."""

    try:
        input_stream = open("/dev/tty", encoding="utf-8", errors="replace")
        output_stream = open("/dev/tty", "w", encoding="utf-8", errors="replace")
    except OSError:
        sys.stderr.write(label)
        sys.stderr.flush()
        return sys.stdin.readline().rstrip("\r\n")

    try:
        prompt_input = create_input(stdin=input_stream)
        prompt_output = create_output(stdout=output_stream)
        session: PromptSession[str] = PromptSession(
            input=prompt_input,
            output=prompt_output,
        )
        return session.prompt(label)
    finally:
        input_stream.close()
        output_stream.close()
