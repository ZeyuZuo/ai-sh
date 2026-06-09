"""Read and write ai-sh configuration."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ai_sh.exceptions import ConfigError

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only exercised on Python 3.10
    import tomli as tomllib

CONFIG_DIR = Path.home() / ".ai-sh"
CONFIG_PATH = CONFIG_DIR / "config.toml"
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

    default_confirm: Literal["y", "n"] = "n"
    history_limit: int = 50
    context_commands: int = 5
    language: Literal["zh", "en", "auto"] = "zh"


@dataclass(frozen=True)
class SafetyConfig:
    """Configuration for local safety checks."""

    hard_block_enabled: bool = True


@dataclass(frozen=True)
class Config:
    """Complete ai-sh configuration."""

    api: ApiConfig = ApiConfig()
    behavior: BehaviorConfig = BehaviorConfig()
    safety: SafetyConfig = SafetyConfig()
    path: Path = CONFIG_PATH


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load configuration, applying defaults and environment overrides."""

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
    safety_data = _section(data, "safety")

    api_key = _api_key_from_sources(api_data)

    return Config(
        api=ApiConfig(
            base_url=_str(api_data, "base_url", DEFAULT_BASE_URL),
            model=_str(api_data, "model", DEFAULT_MODEL),
            api_key=api_key,
        ),
        behavior=BehaviorConfig(
            default_confirm=_confirm_choice(behavior_data.get("default_confirm", "n")),
            history_limit=_positive_int(behavior_data, "history_limit", 50),
            context_commands=_positive_int(behavior_data, "context_commands", 5),
            language=_language(behavior_data.get("language", "zh")),
        ),
        safety=SafetyConfig(
            hard_block_enabled=bool(safety_data.get("hard_block_enabled", True))
        ),
        path=path,
    )


def ensure_default_config(path: Path = CONFIG_PATH) -> Path:
    """Create a default config file if it does not exist."""

    if path.exists():
        return path
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    content = f"""[api]
base_url = "{DEFAULT_BASE_URL}"
model = "{DEFAULT_MODEL}"
api_key = ""

[behavior]
default_confirm = "n"
history_limit = 50
context_commands = 5
language = "zh"

[safety]
hard_block_enabled = true
"""
    path.write_text(content, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def require_api_key(config: Config) -> str:
    """Return the configured API key or raise a user-facing error."""

    if config.api.api_key:
        return config.api.api_key
    raise ConfigError(
        "未配置 SiliconFlow API Key。请 export SILICONFLOW_API，"
        "或在当前目录/.env、~/.ai-sh/.env 中写入 SILICONFLOW_API=...，"
        "或在 ~/.ai-sh/config.toml 的 [api].api_key 中配置。"
    )


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


def _confirm_choice(value: object) -> Literal["y", "n"]:
    return "y" if value == "y" else "n"


def _language(value: object) -> Literal["zh", "en", "auto"]:
    return value if value in {"zh", "en", "auto"} else "zh"
