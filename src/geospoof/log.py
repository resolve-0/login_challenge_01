"""structlog configuration for geospoof."""

import logging

import structlog


def setup(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.WARNING
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[structlog.dev.ConsoleRenderer()],
        logger_factory=structlog.PrintLoggerFactory(),
    )
