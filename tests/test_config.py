import os
import stat

from ai_sh.config import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    ensure_default_config,
    load_config,
)


def test_load_config_defaults_and_env_override(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("SILICONFLOW_API", "secret-from-env")

    config = load_config(config_path)

    assert config.api.base_url == DEFAULT_BASE_URL
    assert config.api.model == DEFAULT_MODEL
    assert config.api.api_key == "secret-from-env"
    assert config.behavior.default_confirm == "n"


def test_load_config_ignores_empty_env_and_reads_dotenv(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text('SILICONFLOW_API="secret-from-dotenv"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SILICONFLOW_API", "")

    config = load_config(config_path)

    assert config.api.api_key == "secret-from-dotenv"


def test_load_config_reads_file_values(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SILICONFLOW_API", raising=False)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [api]
        base_url = "https://example.test/v1"
        model = "custom-model"
        api_key = "file-key"

        [behavior]
        default_confirm = "y"
        history_limit = 12
        context_commands = 3
        language = "en"

        [safety]
        hard_block_enabled = false
        """,
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.api.base_url == "https://example.test/v1"
    assert config.api.model == "custom-model"
    assert config.api.api_key == "file-key"
    assert config.behavior.history_limit == 12
    assert config.behavior.context_commands == 3
    assert config.behavior.language == "en"
    assert config.safety.hard_block_enabled is False


def test_ensure_default_config_uses_600_permissions(tmp_path) -> None:
    config_path = tmp_path / ".ai-sh" / "config.toml"

    ensure_default_config(config_path)

    mode = stat.S_IMODE(os.stat(config_path).st_mode)
    assert mode == 0o600
    assert "SILICONFLOW_API" not in config_path.read_text(encoding="utf-8")
