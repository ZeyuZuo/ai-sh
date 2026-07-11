"""Read and write tmksh configuration."""

from __future__ import annotations

import os
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tmksh.exceptions import ConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - only exercised on Python 3.10
    import tomli as tomllib

CONFIG_DIR = Path.home() / ".tmksh"
CONFIG_PATH = CONFIG_DIR / "config.toml"
LEGACY_CONFIG_DIR = Path.home() / ".ai-sh"
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "deepseek-ai/DeepSeek-V3.2"
API_KEY_ENV = "SILICONFLOW_API"


@dataclass(frozen=True)
class ApiConfig:
    """Configuration for the OpenAI-compatible API."""

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = ""


@dataclass(frozen=True)
class BehaviorConfig:
    """Configuration for command generation and interaction behavior."""

    history_limit: int = 50
    language: Literal["zh", "en", "auto"] = "zh"


@dataclass(frozen=True)
class Config:
    """Complete tmksh configuration."""

    api: ApiConfig = ApiConfig()
    behavior: BehaviorConfig = BehaviorConfig()
    path: Path = CONFIG_PATH


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load configuration, applying defaults and environment overrides."""

    if path == CONFIG_PATH:
        migrate_legacy_state()

    data: dict[str, object] = {}
    if path.exists():
        try:
            with path.open("rb") as config_file:
                raw = tomllib.load(config_file)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"配置文件格式错误：{path}") from exc
        except OSError as exc:
            raise ConfigError(f"无法读取配置文件：{path}") from exc
        if not isinstance(raw, dict):
            raise ConfigError(f"配置文件内容无效：{path}")
        data = raw

    api_data = _section(data, "api")
    behavior_data = _section(data, "behavior")
    api_key = _api_key_from_sources(api_data)

    return Config(
        api=ApiConfig(
            base_url=_str(api_data, "base_url", DEFAULT_BASE_URL),
            model=_str(api_data, "model", DEFAULT_MODEL),
            api_key=api_key,
        ),
        behavior=BehaviorConfig(
            history_limit=_positive_int(behavior_data, "history_limit", 50),
            language=_language(behavior_data.get("language", "zh")),
        ),
        path=path,
    )


def ensure_default_config(path: Path = CONFIG_PATH) -> Path:
    """Create a default config file if it does not exist."""

    if path == CONFIG_PATH:
        migrate_legacy_state()
    if path.exists():
        return path
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    content = f"""[api]
base_url = "{DEFAULT_BASE_URL}"
model = "{DEFAULT_MODEL}"
api_key = ""

[behavior]
history_limit = 50
language = "zh"
"""
    path.write_text(content, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def migrate_legacy_state(
    legacy_dir: Path = LEGACY_CONFIG_DIR,
    target_dir: Path = CONFIG_DIR,
) -> tuple[str, ...]:
    """Copy legacy local state into the tmksh directory without overwriting files."""

    if not legacy_dir.is_dir() or legacy_dir.is_symlink():
        return ()

    migrated: list[str] = []
    for name in ("config.toml", ".env", "history.json"):
        source = legacy_dir / name
        target = target_dir / name
        if not source.is_file() or source.is_symlink() or target.exists():
            continue
        try:
            target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            target_dir.chmod(stat.S_IRWXU)
            shutil.copyfile(source, target)
            target.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:
            raise ConfigError(f"无法迁移旧配置文件：{source}") from exc
        migrated.append(name)
    return tuple(migrated)


def write_config(
    *,
    base_url: str,
    model: str,
    api_key: str,
    path: Path = CONFIG_PATH,
    history_limit: int = 50,
    language: Literal["zh", "en", "auto"] = "zh",
) -> Path:
    """Write a complete config file with private permissions."""

    if not base_url.strip():
        raise ConfigError("base_url 不能为空。")
    if not model.strip():
        raise ConfigError("model 不能为空。")
    if not api_key.strip():
        raise ConfigError("api_key 不能为空。")

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    content = f"""[api]
base_url = "{_escape_toml_string(base_url.strip())}"
model = "{_escape_toml_string(model.strip())}"
api_key = "{_escape_toml_string(api_key.strip())}"

[behavior]
history_limit = {history_limit}
language = "{language}"
"""
    path.write_text(content, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def require_api_key(config: Config) -> str:
    """Return the configured API key or raise a user-facing error."""

    if config.api.api_key:
        return config.api.api_key
    raise ConfigError(
        "未配置 API Key。请运行 `tmksh config` 写入 base_url、model 和 api_key，"
        "或 export SILICONFLOW_API。"
    )


def validate_api_config(config: Config) -> None:
    """Validate that base URL, model, and API key are usable."""

    if not config.api.base_url.strip():
        raise ConfigError("未配置 base_url。请运行 `tmksh config`。")
    if not config.api.model.strip():
        raise ConfigError("未配置 model。请运行 `tmksh config`。")
    require_api_key(config)


def _section(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key, {})
    return value if isinstance(value, dict) else {}


def _str(data: dict[str, object], key: str, default: str) -> str:
    value = data.get(key, default)
    return value if isinstance(value, str) else default


def _api_key_from_sources(api_data: dict[str, object]) -> str:
    env_value = os.getenv(API_KEY_ENV)
    if env_value and env_value.strip():
        return env_value.strip()

    dotenv_value = _read_dotenv_key(Path.cwd() / ".env") or _read_dotenv_key(
        CONFIG_DIR / ".env"
    )
    if dotenv_value:
        return dotenv_value

    return _str(api_data, "api_key", "").strip()


def _read_dotenv_key(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    prefix = f"{API_KEY_ENV}="
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.strip()
    return ""


def _positive_int(data: dict[str, object], key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, int) and value > 0:
        return value
    return default


def _language(value: object) -> Literal["zh", "en", "auto"]:
    return value if value in {"zh", "en", "auto"} else "zh"


def _escape_toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
