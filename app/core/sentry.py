"""Sentry observability wrapper."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask


def init_sentry(app: "Flask") -> None:
    """Initialize Sentry with Flask + SQLAlchemy integrations if SENTRY_DSN is set."""
    dsn = app.config.get("SENTRY_DSN")
    if not dsn:
        return

    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=app.config.get("SENTRY_ENVIRONMENT", "production"),
        integrations=[FlaskIntegration(), SqlalchemyIntegration()],
        traces_sample_rate=app.config.get("SENTRY_TRACES_SAMPLE_RATE", 0.1),
        profiles_sample_rate=app.config.get("SENTRY_PROFILES_SAMPLE_RATE", 0.1),
    )


def set_sentry_user(user) -> None:
    """Attach the current user context to Sentry errors."""
    try:
        import sentry_sdk
    except ImportError:
        return

    if not user or not user.is_authenticated:
        sentry_sdk.set_user(None)
        return

    sentry_sdk.set_user(
        {
            "id": str(getattr(user, "id", "")),
            "email": getattr(user, "email", None),
            "role": getattr(user.role, "value", str(getattr(user, "role", ""))),
        }
    )


def capture_exception(error: BaseException) -> None:
    """Capture an exception in Sentry when available."""
    try:
        import sentry_sdk
    except ImportError:
        return
    sentry_sdk.capture_exception(error)


def capture_message(message: str, level: str = "info") -> None:
    """Capture a message in Sentry when available."""
    try:
        import sentry_sdk
    except ImportError:
        return
    sentry_sdk.capture_message(message, level=level)