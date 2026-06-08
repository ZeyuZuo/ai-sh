from ai_sh import ui


def test_prompt_caution_confirm_requires_y(monkeypatch) -> None:
    monkeypatch.setattr(ui.console, "input", lambda prompt: "n")

    assert ui.prompt_caution_confirm() is False


def test_prompt_caution_confirm_accepts_y(monkeypatch) -> None:
    monkeypatch.setattr(ui.console, "input", lambda prompt: "y")

    assert ui.prompt_caution_confirm() is True
