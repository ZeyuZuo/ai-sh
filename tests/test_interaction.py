import pytest

from tmksh.interaction import (
    HELP_TEXT,
    parse_user_directive,
    unknown_directive_message,
)


def test_parse_natural_language_without_guessing_directives() -> None:
    directive = parse_user_directive("修复上一条命令")

    assert directive.kind == "natural"
    assert directive.argument == "修复上一条命令"


@pytest.mark.parametrize(
    ("value", "kind", "argument"),
    [
        ("  /FIX   不要使用 pip  ", "fix", "不要使用 pip"),
        ("/EXPLAIN why this pipe", "explain", "why this pipe"),
        (" /Check   portability ", "check", "portability"),
        ("/NEW list files", "new", "list files"),
        ("/ask what is rebase", "ask", "what is rebase"),
        ("/HELP", "help", ""),
    ],
)
def test_parse_all_supported_directives(value: str, kind: str, argument: str) -> None:
    directive = parse_user_directive(value)

    assert directive.kind == kind
    assert directive.argument == argument


def test_parse_similar_slash_name_as_unknown_directive() -> None:
    directive = parse_user_directive("/fix-now")

    assert directive.kind == "unknown"
    assert directive.argument == ""
    assert directive.name == "/fix-now"


@pytest.mark.parametrize(
    "value",
    [
        "/usr/bin/env python",
        "./script.sh --help",
        "/路径/脚本",
        "/123",
    ],
)
def test_parse_paths_and_non_english_names_as_natural_language(value: str) -> None:
    directive = parse_user_directive(value)

    assert directive.kind == "natural"
    assert directive.argument == value


def test_unknown_directive_message_includes_close_match_and_local_help() -> None:
    message = unknown_directive_message("/expalin")

    assert "未知指令：/expalin" in message
    assert "你是否想使用：/explain" in message
    assert HELP_TEXT in message
    assert "/help" in message
