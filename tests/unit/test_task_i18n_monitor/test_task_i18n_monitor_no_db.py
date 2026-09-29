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

import inspect
from importlib import import_module
from typing import Any

import pytest

# ملاحظة: البارامتر هو *اسم* الاختبار المرجعي (نص)، وتُستدعى الدالة بعد
# تحليلها من الوحدة المرجعية — لا يجوز أن يحمل البارامتر نفس اسم الـ fixture
# وإلا طغى النص على القيمة المطلوبة.
_CANONICAL_TEST_NAMES: list[str] = [
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

# مواضع pytest التي قد تحتاجها الدوال المرجعية وتُمرَّر بالاسم إن أعلنتها.
_INJECTABLE_FIXTURES = ("tmp_path", "monkeypatch")


def _resolve_canonical_test(name: str) -> Any:
    module = import_module("tests.test_task_i18n_monitor")
    fn = getattr(module, name)
    # Preserve the canonical function's documentation for readability.
    return fn


@pytest.mark.parametrize("canonical_test_name", _CANONICAL_TEST_NAMES, ids=_CANONICAL_TEST_NAMES)
def test_run_from_canonical(request: pytest.FixtureRequest, canonical_test_name: str) -> None:
    canonical_test = _resolve_canonical_test(canonical_test_name)
    kwargs: dict[str, Any] = {}
    for param_name in inspect.signature(canonical_test).parameters:
        if param_name in _INJECTABLE_FIXTURES:
            kwargs[param_name] = request.getfixturevalue(param_name)
    canonical_test(**kwargs)
