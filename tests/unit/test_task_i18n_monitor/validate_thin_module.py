"""
Thin validation helper for the i18n task test module.

This script is used only for low-level QA. It confirms that the canonical
test definitions are importable and that the expected public test names are
present, without touching pytest's session-scoped conftest.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Sequence

# Ensure the repository root is on the import path for this QA helper only.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path and "." not in sys.path:
    sys.path.insert(0, str(_ROOT))
elif "." not in sys.path:
    sys.path.insert(0, str(_ROOT))

EXPECTED: Sequence[str] = (
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
)


def main() -> int:
    try:
        mod = importlib.import_module("tests.test_task_i18n_monitor")
    except Exception as exc:  # noqa: BLE001
        print("IMPORT_FAILED:", exc)
        return 3

    names = [n for n in dir(mod) if n.startswith("test_")]
    present = set(names)
    missing = [n for n in EXPECTED if n not in present]

    if missing:
        print("MISSING EXPECTED TESTS:", *missing, sep="\n  ")
        return 2

    print("OK — all expected test names present in the canonical module.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
