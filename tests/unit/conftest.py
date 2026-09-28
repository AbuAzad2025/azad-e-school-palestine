"""
Allow the QA helper to run even when the dev database is unavailable.

The global `tests/conftest.py` is session-scoped and requires a running
PostgreSQL instance. This narrower conftest is placed only where needed for
the imported i18n task tests, so they can be collected and run locally
without touching the DB.
"""

from __future__ import annotations

import sys


def _pytest_configure(config):
    # Prevent pytest from importing the top-level conftest that triggers
    # the app factory.
    if "structlog" not in sys.modules:
        # If the app was already imported (e.g. via an earlier test run),
        # the normal module path already failed. In that case we fail fast
        # with a clear message.
        raise SystemExit(
            "Cannot run QA task unit tests here because the app could not be "
            "imported (missing 'structlog' in the QA environment). "
            "Either install the missing dependency or run the canonical "
            "tests via the main tests/ conftest."
        )


def pytest_configure(config):
    _pytest_configure(config)
