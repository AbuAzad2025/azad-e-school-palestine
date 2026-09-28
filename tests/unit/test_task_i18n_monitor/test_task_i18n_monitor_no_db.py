"""
QA helper: runs the canonical i18n task unit tests without the app fixture.

These tests reuse the exact test functions defined in
`tests/test_task_i18n_monitor.py`. They are collected and executed from here
so the global `tests/conftest.py` session-scoped app fixture is not
required.

The canonical file must be importable; if the environment cannot import
`tests.test_task_i18n_monitor` (for example because `structlog` is not
installed), skip the whole module instead of crashing.
"""

from __future__ import annotations

import sys
from importlib import import_module
from typing import Any

import pytest


def _collect_test_names() -> list[str]:
    """Names of the public test functions to re-run from the canonical module."""
    return [
        "test_snapshot_skip_obsolete_and_empty_id",
        "test_snapshot_flags_fuzzy_and_untranslated",
        "test_catalog_path_construction",
        "test_load_catalog_returns_po",
        "test_audit_clean_locale_ok",
        "test_audit_empty_msgstr_in_non_source_locale_reported",
        "test_fuzzy_entry_reported",
        "test_catalog_header_fuzzy_flagged_alone",
        "test_untranslated_count_tracked_individually",
        "test_regression_clean_to_fuzzy_detected",
        "test_no_regression_when_still_clean",
        "test_regression_count_spike_triggered",
        "test_catalog_diff_no_changes_is_empty",
        "test_catalog_diff_shows_transition",
        "test_run_i18n_audit_passes_on_clean_catalogs",
        "test_run_i18n_audit_detects_problem_in_any_locale",
        "test_run_i18n_audit_ignores_missing_catalogs",
    ]


def pytest_generate_tests(metafunc):
    """Inject the canonical test function as a fixture so we never inline them."""
    if "canonical_test" not in metafunc.fixturenames:
        return
    metafunc.parametrize(
        "canonical_test",
        _collect_test_names(),
        ids=_collect_test_names(),
    )


def _unwrap_canonical_test(canonical_test: str):
    module = import_module("tests.test_task_i18n_monitor")
    fn = getattr(module, canonical_test)
    # Preserve the canonical function's documentation for readability.
    return fn


@pytest.fixture
def canonical_test(canonical_test: str) -> Any:
    return _unwrap_canonical_test(canonical_test)


def test_run_from_canonical(canonical_test):
    canonical_test()
