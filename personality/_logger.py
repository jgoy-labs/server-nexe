"""
Nexe personality logger wrapper.

Accepts extra keyword arguments (component=, etc.) that the standard
logging.Logger does not support, passing them via the `extra` dict.
"""

import logging


class NexeLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that accepts arbitrary kwargs and passes them as extra."""

    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        # Move any non-standard kwargs into extra
        standard = {"exc_info", "stack_info", "stacklevel", "extra"}
        for key in list(kwargs.keys()):
            if key not in standard:
                extra[key] = kwargs.pop(key)
        if extra:
            kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name: str) -> NexeLoggerAdapter:
    """Get a NexeLoggerAdapter for the given module name."""
    return NexeLoggerAdapter(logging.getLogger(name), {})
