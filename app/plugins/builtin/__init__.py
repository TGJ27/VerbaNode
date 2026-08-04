from app.plugins.builtin.conversation import StopConversationPlugin
from app.plugins.builtin.location import LocationPlugin
from app.plugins.builtin.time import CurrentTimePlugin
from app.plugins.builtin.weather import WeatherPlugin


def builtin_plugins():
    """Create a fresh ordered set of built-in capability plugins."""
    return (
        CurrentTimePlugin(),
        LocationPlugin(),
        WeatherPlugin(),
        StopConversationPlugin(),
    )


__all__ = [
    "CurrentTimePlugin",
    "LocationPlugin",
    "WeatherPlugin",
    "StopConversationPlugin",
    "builtin_plugins",
]
