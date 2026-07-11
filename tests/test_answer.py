from io import BytesIO

from ai_sh.answer import MAX_ASK_STDIN_BYTES, create_answer, read_limited_stdin


def test_read_limited_stdin_preserves_small_utf8_input() -> None:
    value, truncated = read_limited_stdin(BytesIO("日志内容".encode()))

    assert value == "日志内容"
    assert truncated is False


def test_read_limited_stdin_stops_at_byte_limit() -> None:
    stream = BytesIO(b"x" * (MAX_ASK_STDIN_BYTES + 1000))

    value, truncated = read_limited_stdin(stream)

    assert value == "x" * MAX_ASK_STDIN_BYTES
    assert truncated is True
    assert stream.tell() == MAX_ASK_STDIN_BYTES + 1


def test_create_answer_uses_separate_answer_call(monkeypatch, tmp_path) -> None:
    from ai_sh.config import ApiConfig, BehaviorConfig, Config, SafetyConfig

    config = Config(
        api=ApiConfig(api_key="test-key"),
        behavior=BehaviorConfig(language="zh"),
        safety=SafetyConfig(),
        path=tmp_path / "config.toml",
    )
    captured = {}

    def fake_generate(config_arg, messages):
        captured["config"] = config_arg
        captured["messages"] = messages
        return "分析结果"

    monkeypatch.setattr("ai_sh.answer.generate_answer", fake_generate)

    answer = create_answer(
        config,
        "分析日志",
        stdin_context="ERROR connection failed",
    )

    assert answer == "分析结果"
    assert captured["config"] is config
    assert "ERROR connection failed" in captured["messages"][-1]["content"]
