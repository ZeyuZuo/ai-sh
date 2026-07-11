"""Independent natural-language answer orchestration."""

from __future__ import annotations

from typing import BinaryIO

from ai_sh.config import Config
from ai_sh.llm import build_answer_messages, generate_answer

MAX_ASK_STDIN_BYTES = 64 * 1024
_READ_CHUNK_BYTES = 8192


def create_answer(
    config: Config,
    question: str,
    *,
    stdin_context: str = "",
    stdin_truncated: bool = False,
) -> str:
    """Answer a question without command safety, execution, or history paths."""

    messages = build_answer_messages(
        question,
        stdin_context=stdin_context,
        stdin_truncated=stdin_truncated,
        language=config.behavior.language,
    )
    return generate_answer(config, messages)


def read_limited_stdin(stream: BinaryIO) -> tuple[str, bool]:
    """Read stdin incrementally while retaining at most the configured byte limit."""

    chunks: list[bytes] = []
    retained = 0
    truncated = False
    while retained <= MAX_ASK_STDIN_BYTES:
        chunk = stream.read(min(_READ_CHUNK_BYTES, MAX_ASK_STDIN_BYTES + 1 - retained))
        if not chunk:
            break
        chunks.append(chunk)
        retained += len(chunk)
        if retained > MAX_ASK_STDIN_BYTES:
            truncated = True
            break

    payload = b"".join(chunks)[:MAX_ASK_STDIN_BYTES]
    return payload.decode("utf-8", errors="replace"), truncated
