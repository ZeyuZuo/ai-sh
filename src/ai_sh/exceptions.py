"""Project-specific exceptions."""


class AiShError(Exception):
    """Base class for user-facing ai-sh errors."""


class ApiError(AiShError):
    """Raised when the configured AI API cannot return a usable response."""


class ConfigError(AiShError):
    """Raised when configuration is missing or invalid."""


class SafetyBlockedError(AiShError):
    """Raised when a command is blocked by the local safety layer."""


class ExecutionError(AiShError):
    """Raised when command execution fails before a process result exists."""
