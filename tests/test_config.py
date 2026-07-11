import os
import stat

from tmksh.config import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    ensure_default_config,
    load_config,
    migrate_legacy_state,
    validate_api_config,
    write_config,
)
from tmksh.exceptions import ConfigError


def test_load_config_defaults_and_env_override(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("SILICONFLOW_API", "secret-from-env")

    config = load_config(config_path)

    assert config.api.base_url == DEFAULT_BASE_URL
    assert config.api.model == DEFAULT_MODEL
    assert config.api.api_key == "secret-from-env"


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
        history_limit = 12
        language = "en"
        """,
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.api.base_url == "https://example.test/v1"
    assert config.api.model == "custom-model"
    assert config.api.api_key == "file-key"
    assert config.behavior.history_limit == 12
    assert config.behavior.language == "en"


def test_ensure_default_config_uses_600_permissions(tmp_path) -> None:
    config_path = tmp_path / ".tmksh" / "config.toml"

    ensure_default_config(config_path)

    mode = stat.S_IMODE(os.stat(config_path).st_mode)
    assert mode == 0o600
    assert "SILICONFLOW_API" not in config_path.read_text(encoding="utf-8")


def test_write_config_persists_api_settings_with_600_permissions(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("SILICONFLOW_API", raising=False)
    config_path = tmp_path / ".tmksh" / "config.toml"

    write_config(
        base_url="https://api.example.test/v1",
        model="example-model",
        api_key="secret-key",
        path=config_path,
    )

    mode = stat.S_IMODE(os.stat(config_path).st_mode)
    config = load_config(config_path)
    assert mode == 0o600
    assert config.api.base_url == "https://api.example.test/v1"
    assert config.api.model == "example-model"
    assert config.api.api_key == "secret-key"


def test_migrate_legacy_state_copies_private_files_without_overwrite(tmp_path) -> None:
    legacy_dir = tmp_path / ".ai-sh"
    target_dir = tmp_path / ".tmksh"
    legacy_dir.mkdir()
    (legacy_dir / "config.toml").write_text("legacy-config", encoding="utf-8")
    (legacy_dir / "history.json").write_text("[]", encoding="utf-8")
    target_dir.mkdir()
    (target_dir / "config.toml").write_text("new-config", encoding="utf-8")

    migrated = migrate_legacy_state(legacy_dir, target_dir)

    assert migrated == ("history.json",)
    assert (target_dir / "config.toml").read_text(encoding="utf-8") == "new-config"
    assert (target_dir / "history.json").read_text(encoding="utf-8") == "[]"
    assert stat.S_IMODE((target_dir / "history.json").stat().st_mode) == 0o600


def test_validate_api_config_requires_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SILICONFLOW_API", raising=False)
    config = load_config(tmp_path / "missing.toml")

    try:
        validate_api_config(config)
    except ConfigError as exc:
        assert "tmksh config" in str(exc)
    else:
        raise AssertionError("validate_api_config should require api key")
