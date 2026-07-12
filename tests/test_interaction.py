from tmksh.interaction import parse_user_directive


def test_parse_fix_directive_with_optional_supplement() -> None:
    directive = parse_user_directive("  /FIX   不要使用 pip  ")

    assert directive.kind == "fix"
    assert directive.argument == "不要使用 pip"


def test_parse_natural_language_without_guessing_directives() -> None:
    directive = parse_user_directive("修复上一条命令")

    assert directive.kind == "natural"
    assert directive.argument == "修复上一条命令"


def test_parse_similar_slash_name_as_natural_language() -> None:
    directive = parse_user_directive("/fix-now")

    assert directive.kind == "natural"
    assert directive.argument == "/fix-now"
