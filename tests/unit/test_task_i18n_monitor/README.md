# Targeted QA run for imported test helpers

The candidatest file is effectively a thin proxy, so pytest needs a small
conftest stub to prevent the global `tests/conftest.py` from running and
trying to connect to a development database.

To run against a Postgres DB (if one is available):

    .venv/Scripts/python.exe -m pytest tests/unit/test_task_i18n_monitor/test_task_i18n_monitor_no_db.py -v
