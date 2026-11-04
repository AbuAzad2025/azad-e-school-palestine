"""Coverage gaps for app/core/rls.py — policy builders, platform_scope, access_read_scope."""

import pytest


class TestBuildAllPolicyDdl:
    def test_builds_statements_for_existing_tables(self, app):
        from app.core import rls

        with app.app_context():
            statements, skipped = rls.build_all_policy_ddl()
        assert len(statements) > 0
        assert isinstance(skipped, list)

    def test_missing_tables_are_all_skipped(self, app, monkeypatch):
        from app.core import rls

        class _FakeInspector:
            def has_table(self, table):
                return False

            def get_columns(self, table):
                return []

        monkeypatch.setattr("sqlalchemy.inspect", lambda *a, **k: _FakeInspector())
        with app.app_context():
            statements, skipped = rls.build_all_policy_ddl()
        assert statements == []
        registered = rls._TENANT_TABLES + list(rls._INDIRECT_TENANT_TABLES) + rls._USER_SCOPED_TABLES + rls._USER_SCOPED_WITH_TENANT
        assert set(skipped) == set(registered)

    def test_present_raises_are_skipped(self, app, monkeypatch):
        from app.core import rls

        class _BoomInspector:
            def has_table(self, table):
                raise RuntimeError("boom")

            def get_columns(self, table):
                return []

        monkeypatch.setattr("sqlalchemy.inspect", lambda *a, **k: _BoomInspector())
        with app.app_context():
            statements, skipped = rls.build_all_policy_ddl()
        assert statements == []
        assert len(skipped) > 0


class TestEnableRlsHelpers:
    def test_direct_table_with_individual_catalogue_and_coupons(self, app):
        from app.core import rls

        with app.app_context():
            assert rls.enable_rls_on_table("classes", individual_catalogue=True) is True
            assert rls.enable_rls_on_table("discount_codes") is True

    def test_missing_tables_return_false(self, app):
        from app.core import rls

        with app.app_context():
            assert rls.enable_rls_on_table("no_such_table_xyz") is False
            assert rls.enable_rls_on_indirect_table("no_such_table_xyz", "1=1") is False
            assert rls.enable_rls_on_user_scoped_table("no_such_table_xyz") is False

    def test_indirect_table_with_user_owned_arm(self, app):
        from app.core import rls

        with app.app_context():
            assert rls.enable_rls_on_indirect_table("class_members", "SELECT 1") is True

    def test_indirect_table_with_actor_write_arm(self, app):
        from app.core import rls

        with app.app_context():
            assert rls.enable_rls_on_indirect_table("submissions", "SELECT 1") is True

    def test_user_scoped_with_tenant_and_class_arms(self, app):
        from app.core import rls

        with app.app_context():
            assert (
                rls.enable_rls_on_user_scoped_table(
                    "user_role_links",
                    include_tenant_arm=True,
                    include_class_arm="user_role_links.school_id",
                )
                is True
            )


class TestSnapshotsAndHelpers:
    def test_snapshot_reads_gucs_from_db_when_no_flask_context(self, app):
        from sqlalchemy import text

        from app.core import rls
        from app.extensions import db

        with app.app_context():
            db.session.execute(text("SELECT 1"))  # open transaction
            snap = rls._request_guc_snapshot()
            assert set(snap) == set(rls._REQUEST_GUC_NAMES)

    def test_snapshot_fallback_on_broken_g(self, app, monkeypatch):
        from app.core import rls

        class _BadG:
            @property
            def _rls_request_gucs(self):
                raise RuntimeError("boom")

        monkeypatch.setattr("flask.g", _BadG())
        monkeypatch.setattr(rls, "_session_in_transaction", lambda: False)
        snap = rls._request_guc_snapshot()
        assert set(snap) == set(rls._REQUEST_GUC_NAMES)

    def test_read_gucs_from_db_returns_none_on_error(self, app, monkeypatch):
        from app.core import rls

        class _Boom:
            def __call__(self, *a, **k):
                raise RuntimeError("db down")

        monkeypatch.setattr(rls.db.session, "execute", _Boom())
        assert rls._read_gucs_from_db() is None


class TestPlatformScope:
    def test_elevates_open_transaction_and_rolls_back(self, app):
        from sqlalchemy import text

        from app.core import rls
        from app.extensions import db

        with app.app_context():
            db.session.execute(text("SELECT 1"))  # open transaction before scope
            with rls.platform_scope():
                assert getattr(rls._platform_scope, "depth", 0) >= 1
            assert getattr(rls._platform_scope, "depth", 0) == 0

    def test_restore_and_rollback_failures_are_swallowed(self, app, monkeypatch):
        from app.core import rls

        def _boom_rollback():
            raise RuntimeError("rollback boom")

        def _boom_restore(snapshot):
            raise RuntimeError("restore boom")

        monkeypatch.setattr(rls.db.session, "rollback", _boom_rollback)
        monkeypatch.setattr(rls, "_restore_request_gucs", _boom_restore)

        with app.app_context():
            with rls.platform_scope():
                pass  # must not raise


class TestAccessReadScope:
    def test_disallowed_table_raises_value_error(self, app):
        from app.core import rls

        with app.app_context(), pytest.raises(ValueError):
            with rls.access_read_scope("users", 1):
                pass

    def test_get_for_access_check_disallowed_table_raises(self, app):
        from app.core import rls

        class _FakeModel:
            __tablename__ = "users"

        with app.app_context(), pytest.raises(ValueError):
            rls.get_for_access_check(_FakeModel, 1)

    def test_get_for_access_check_missing_row_returns_none(self, app):
        from app.core import rls
        from app.models.content import Lesson

        with app.app_context():
            assert rls.get_for_access_check(Lesson, 999999) is None

    def test_get_for_access_check_eager_loads_and_expunges(self, app):
        from tests.conftest import make_class, make_grade, make_school, make_subject

        sid = make_school(app)
        gid = make_grade(app, sid, grade_level=_next_level(sid))
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        with app.app_context():
            from app.core import rls
            from app.models.class_room import ClassRoom

            row = rls.get_for_access_check(ClassRoom, cid)
            assert row is not None
            assert row.id == cid


def _next_level(_sid):
    import random

    return random.randint(100, 900)


class TestDisableAllRls:
    def test_disable_and_reenable_is_safe(self, app):
        from app.core import rls

        with app.app_context():
            rls.disable_all_rls_policies()
            rls.enable_all_rls_policies()
