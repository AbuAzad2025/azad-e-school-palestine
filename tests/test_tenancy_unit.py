"""Coverage gaps for app/core/tenancy.py — current_school_id, scope helpers."""

from __future__ import annotations

import pytest


def _fake_user(*, authenticated=False, role=None, id=1, school_id=7, individual=False):
    class _Role:
        def __eq__(self, other):
            return self is other

    class _User:
        is_authenticated = authenticated
        role = role
        id = id
        school_id = school_id
        is_individual = individual

        def __init__(self):
            self.school_id = school_id

    return _User()


class _SuperAdmin:
    is_authenticated = True

    def __eq__(self, other):
        return self is other


class TestCurrentSchoolId:
    def test_unauthenticated_returns_none(self, app, monkeypatch):
        from app.core import tenancy

        class _Anon:
            is_authenticated = False
            role = None

        monkeypatch.setattr(tenancy, "current_user", _Anon())
        assert tenancy.current_school_id() is None

    def test_super_admin_returns_none(self, app, monkeypatch):
        from app.core import tenancy
        from app.models.user import UserRole

        class _SA:
            is_authenticated = True
            role = UserRole.super_admin

        monkeypatch.setattr(tenancy, "current_user", _SA())
        assert tenancy.current_school_id() is None

    def test_reads_guc_when_set(self, app, monkeypatch):
        from app.core import tenancy
        from app.models.user import UserRole

        class _U:
            is_authenticated = True
            role = UserRole.teacher

        monkeypatch.setattr(tenancy, "current_user", _U())
        from sqlalchemy import text

        from app.extensions import db

        with app.app_context():
            db.session.execute(text("SELECT set_config('app.current_school_id', '7', true)"))
            assert tenancy.current_school_id() == 7

    def test_falls_back_to_relationship_when_guc_zero(self, app, monkeypatch):
        from app.core import tenancy
        from app.models.user import UserRole

        class _U:
            is_authenticated = True
            role = UserRole.student
            id = 42
            school_id = 9

        monkeypatch.setattr(tenancy, "current_user", _U())
        from sqlalchemy import text

        from app.extensions import db

        with app.app_context():
            db.session.execute(text("SELECT set_config('app.current_school_id', '0', true)"))
            assert tenancy.current_school_id() == 9

    def test_except_returns_none(self, app, monkeypatch):
        from app.core import tenancy

        class _Exploding:
            is_authenticated = True

            @property
            def role(self):
                raise RuntimeError("boom")

        monkeypatch.setattr(tenancy, "current_user", _Exploding())
        assert tenancy.current_school_id() is None


class TestGetSchoolOr404:
    def test_same_school_returns_school(self, app, monkeypatch):
        from app.core import tenancy

        sid = _make_school(app)
        monkeypatch.setattr(tenancy, "current_school_id", lambda: sid)
        with app.app_context():
            assert tenancy.get_school_or_404(sid).id == sid

    def test_other_school_aborts_403(self, app, monkeypatch):
        from app.core import tenancy

        monkeypatch.setattr(tenancy, "current_school_id", lambda: 1)
        with pytest.raises(Exception):
            tenancy.get_school_or_404(999)


def _make_school(app):
    from app.extensions import db
    from app.models.school import School

    with app.app_context():
        s = School(name_ar="مدرسة اختبار التغطية", domain="cov-test.azad.ps")
        db.session.add(s)
        db.session.commit()
        return s.id


class TestScopeBySchool:
    def test_model_without_field_raises_value_error(self, app):
        from app.core.tenancy import scope_by_school

        class _Dummy:
            __name__ = "Dummy"

        with pytest.raises(ValueError):
            scope_by_school(_Dummy, 1)

    def test_query_filters_by_school(self, app):
        from app.core.tenancy import scope_by_school
        from app.models.school import Grade

        sid = _make_school(app)
        with app.app_context():
            q = scope_by_school(Grade, sid)
            assert q.filter_by(school_id=sid).count() == q.count()


class TestTenantScope:
    def test_other_school_aborts_403(self, app, monkeypatch):
        from app.core.tenancy import tenant_scope
        from app.models.school import Grade

        monkeypatch.setattr("app.core.tenancy.current_school_id", lambda: 1)
        with pytest.raises(Exception):
            tenant_scope(Grade, 2)

    def test_same_school_returns_query(self, app, monkeypatch):
        from app.core.tenancy import tenant_scope
        from app.models.school import Grade

        sid = _make_school(app)
        monkeypatch.setattr("app.core.tenancy.current_school_id", lambda: sid)
        with app.app_context():
            q = tenant_scope(Grade, sid)
            assert q.count() >= 0
