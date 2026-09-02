"""Celery application factory — async task pipeline for Azad E-School.

P4-01: Celery integrated with Flask app context via Task base class.
P4-02: All tasks execute within Flask app context (db, config, extensions).
P4-03: Structured logging + correlation IDs propagated to worker tasks.

Usage:
    from app.tasks import celery_app, dispatch_notification
    dispatch_notification.delay(user_id=42, type="grade", title="New grade")
"""

from __future__ import annotations

import os
from typing import Any

try:
    from celery import Celery
    from celery.signals import task_postrun, task_prerun

    _HAS_CELERY = True
except ImportError:
    _HAS_CELERY = False

if _HAS_CELERY:
    # ─── Celery App Factory ────────────────────────────────────────────
    celery_app = Celery("azad_eschool")

    # Configuration — loaded from environment or Flask config
    celery_app.config_from_object(
        {
            "broker_url": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            "result_backend": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            "task_serializer": "json",
            "result_serializer": "json",
            "accept_content": ["json"],
            "timezone": "UTC",
            "enable_utc": True,
            "task_track_started": True,
            "task_time_limit": 300,  # 5 min hard limit
            "task_soft_time_limit": 240,  # 4 min soft limit
            "task_acks_late": True,  # Ack after execution (not before)
            "task_reject_on_worker_lost": True,  # Re-queue on crash
            "task_default_retry_delay": 60,
            "task_max_retries": 3,
            "worker_prefetch_multiplier": 1,  # One task at a time per worker
            "worker_max_tasks_per_child": 100,  # Prevent memory leaks
            "broker_transport_options": {
                "visibility_timeout": 3600,  # 1 hour
            },
        }
    )

    # Auto-discover tasks in all task modules
    celery_app.autodiscover_tasks(
        [
            "app.tasks.notifications",
            "app.tasks.reports",
            "app.tasks.grading",
        ]
    )

    def init_celery(app: Any) -> None:
        """Bind Celery to a Flask app and configure Flask app context for tasks.

        Called from create_app() after extensions are initialized.

        This ensures every task runs with access to:
        - Flask app context (current_app)
        - SQLAlchemy session (db)
        - Configuration (app.config)
        - Login manager
        """
        celery_app.conf.update(
            broker_url=app.config.get("REDIS_URL", "redis://localhost:6379/0"),
            result_backend=app.config.get("REDIS_URL", "redis://localhost:6379/0"),
        )
        celery_app.flask_app = app

    # ─── Flask App Context for Tasks ───────────────────────────────────

    class ContextTask:
        """Mixin that wraps task execution in Flask app context.

        Usage as Celery task base:
            @celery_app.task(base=ContextTask, bind=True)
            def my_task(self, user_id):
                ...

        This ensures the task runs inside Flask's application context,
        giving access to db, config, and all extensions.
        """

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            flask_app = getattr(celery_app, "flask_app", None)
            if flask_app is not None:
                with flask_app.app_context():
                    return super().__call__(*args, **kwargs)  # type: ignore[misc]
            return super().__call__(*args, **kwargs)  # type: ignore[misc]

    # ─── Task Signals — Structured Logging ─────────────────────────────

    @task_prerun.connect
    def _task_prerun_handler(sender: Any, task_id: str, **kwargs: Any) -> None:
        """Log task start with structured context."""
        from app.core.logging import get_logger

        logger = get_logger("celery.task")
        logger.info(
            "task_started",
            task_name=sender.name,
            task_id=task_id,
        )

    @task_postrun.connect
    def _task_postrun_handler(
        sender: Any,
        task_id: str,
        retval: Any,
        state: str,
        **kwargs: Any,
    ) -> None:
        """Log task completion with structured context."""
        from app.core.logging import get_logger

        logger = get_logger("celery.task")
        log_fn = logger.info if state == "SUCCESS" else logger.error
        log_fn(
            "task_completed",
            task_name=sender.name,
            task_id=task_id,
            state=state,
        )

else:
    # Celery not installed — provide stub for import compatibility
    celery_app = None

    def init_celery(app: Any) -> None:
        """No-op when celery is not installed."""

    class ContextTask:  # type: ignore[no-redef]
        """Stub when celery is not installed."""
