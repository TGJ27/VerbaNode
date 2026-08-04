class PluginError(Exception):
    """Base exception for plugin discovery and lifecycle failures."""


class PluginManifestError(PluginError):
    """Raised when an external plugin manifest is invalid."""


class PluginLoadError(PluginError):
    """Raised when an external plugin module cannot be imported or instantiated."""


class PluginCompatibilityError(PluginError):
    """Raised when a plugin targets an unsupported SDK version."""
