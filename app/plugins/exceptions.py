class PluginError(Exception):
    """Base exception for plugin discovery and lifecycle failures."""


class PluginManifestError(PluginError):
    """Raised when an external plugin manifest is invalid."""


class PluginLoadError(PluginError):
    """Raised when an external plugin module cannot be imported or instantiated."""


class PluginCompatibilityError(PluginError):
    """Raised when a plugin targets an unsupported SDK version."""


class PluginSchemaError(PluginError):
    """Raised when a plugin exposes an invalid LLM tool schema."""


class PluginUnavailableError(PluginError):
    """Raised when a plugin is disabled, unhealthy, or reloading."""
