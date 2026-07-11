"""Project-specific exceptions."""


class TmkshError(Exception):
    """Base class for user-facing tmksh errors."""


class ApiError(TmkshError):
    """Raised when the configured AI API cannot return a usable response."""


class ConfigError(TmkshError):
    """Raised when configuration is missing or invalid."""


class SafetyBlockedError(TmkshError):
    """Raised when a command is blocked by the local safety layer."""


class ExecutionError(TmkshError):
    """Raised when command execution fails before a process result exists."""
