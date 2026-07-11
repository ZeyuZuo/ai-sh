from tmksh.executor import execute_command, summarize_execution


def test_execute_command_captures_output() -> None:
    result = execute_command("printf hello")

    assert result.exit_code == 0
    assert result.stdout == "hello"
    assert result.stderr == ""


def test_execute_command_timeout_is_bounded() -> None:
    result = execute_command("sleep 2", timeout=1)

    assert result.timed_out is True
    assert result.exit_code == 124


def test_execute_command_timeout_decodes_partial_output() -> None:
    result = execute_command("printf hello; sleep 2", timeout=1)

    assert result.timed_out is True
    assert result.stdout == "hello"
    assert isinstance(result.stdout, str)


def test_summarize_execution_truncates_output() -> None:
    result = execute_command("printf 1234567890")

    assert "...[truncated]" in summarize_execution(result, limit=3)
