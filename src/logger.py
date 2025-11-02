"""Structured logging utilities for Plex Dubs application."""

from __future__ import annotations

from typing import Any
from logging import Logger


def _format_value(value: Any) -> str:
    """Format a value for key-value logging.

    Args:
        value: Value to format.

    Returns:
        Formatted string representation.
    """
    if isinstance(value, str):
        # Quote strings that contain spaces
        if ' ' in value or '=' in value:
            return f'"{value}"'
        return value
    elif isinstance(value, bool):
        return str(value).lower()
    elif value is None:
        return 'null'
    else:
        return str(value)


def _format_kv_pairs(**kwargs: Any) -> str:
    """Format keyword arguments as key=value pairs.

    Args:
        **kwargs: Key-value pairs to format.

    Returns:
        Formatted string of key=value pairs.
    """
    pairs = [f"{key}={_format_value(value)}" for key, value in kwargs.items()]
    return ' '.join(pairs)


def log_event(logger: Logger, event: str, **data: Any) -> None:
    """Log an event with structured key-value data.

    Args:
        logger: Logger instance to use.
        event: Event name/type.
        **data: Additional key-value pairs to log.

    Example:
        log_event(logger, "webhook.received", source="sonarr", event="Download")
    """
    if data:
        logger.info(f"{event}\n  {_format_kv_pairs(**data)}")
    else:
        logger.info(event)


def log_action(logger: Logger, action: str, **data: Any) -> None:
    """Log a processing action with structured data.

    Args:
        logger: Logger instance to use.
        action: Action being performed.
        **data: Additional context as key-value pairs.

    Example:
        log_action(logger, "add_to_collection", media="Show S01E01", status="success")
    """
    data['action'] = action
    logger.info(f"processing\n  {_format_kv_pairs(**data)}")


def log_error(logger: Logger, error: str, **data: Any) -> None:
    """Log an error with structured context.

    Args:
        logger: Logger instance to use.
        error: Error message.
        **data: Additional error context.

    Example:
        log_error(logger, "Connection failed", service="plex", attempt=3)
    """
    if data:
        logger.error(f"{error}\n  {_format_kv_pairs(**data)}")
    else:
        logger.error(error)


def log_warning(logger: Logger, warning: str, **data: Any) -> None:
    """Log a warning with structured context.

    Args:
        logger: Logger instance to use.
        warning: Warning message.
        **data: Additional warning context.

    Example:
        log_warning(logger, "Retrying connection", attempt=2, max_retries=5)
    """
    if data:
        logger.warning(f"{warning}\n  {_format_kv_pairs(**data)}")
    else:
        logger.warning(warning)
