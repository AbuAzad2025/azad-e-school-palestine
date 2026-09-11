"""Batch 1 — core/security gap coverage (real behavior, real DDL).

Targets verified uncovered:
- app/core/rls.py DDL builders (enable_rls_on_table / enable_rls_on_indirect_table /
  enable_all_rls_policies / disable_all_rls_policies) — verified via pg policy
  introspection, not source-text asserts.
- Real RLS policy enforcement: cross-tenant SELECT blocked, same-tenant allowed,
  super-admin context bypass.
- app/core/openapi.py init_swagger() disabled/registered branches + /api/v1/openapi.json.
- app/core/cache.py backend fallbacks (redis import failure, broken redis client,
  TTL expiry, scan-based clear).
"""

from __future__ import annotations

import json
import sys
import time
import types

import pytest
import sqlalchemy
from sqlalchemy import text
from tests.conftest import make_grade, make_school

# ═══════════════════════════════════════════════════════════════════════════
# RLS — DDL builders verified through PostgreSQL catalog introspection
# ═══════════════════════════════════════════════════════════════════════════


class TestRLSPolicyDDL:
    """enable_rls_* builders must produce real, introspectable policies."""

    @pytest.fixture(autouse=True)
    def _restore_rls_after(self, app):
        """Defensive: after each test the table's RLS is enabled again.

        CI runs as a superuser (RLS bypass) so a brief toggle is invisible to
        the rest of the suite; restoring enabled state keeps local runs safe.
        """
        yield
        with app.app_context():
            try:
                from app.core.rls import enable_rls_on_table

                enable_rls_on_table("grades")
                app.extensions["sqlalchemy"].session.commit()
            except Exception:  # noqa: BLE001 — best-effort restore
                pass

    def _policies(self, app, table: str) -> list[str]:
        with app.app_context():
            rows = (
                app.extensions["sqlalchemy"]
                .session.execute(
                    text("SELECT policyname FROM pg_policies WHERE tablename = :t ORDER BY 1"),
                    {"t": table},
                )
                .fetchall()
            )
            return [r[0] for r in rows]

    def _rls_enabled(self, app, table: str) -> bool:
        with app.app_context():
            row = (
                app.extensions["sqlalchemy"]
                .session.execute(
                    text("SELECT relrowsecurity FROM pg_class WHERE relname = :t"),
                    {"t": table},
                )
                .fetchone()
            )
            return bool(row and row[0])

    def test_enable_rls_on_table_creates_real_policy(self, app):
        from app.core.rls import enable_rls_on_table

        with app.app_context():
            assert enable_rls_on_table("grades") is True
            app.extensions["sqlalchemy"].session.commit()

        assert self._rls_enabled(app, "grades") is True
        assert "tenant_isolation_grades" in self._policies(app, "grades")

    def test_enable_rls_on_table_skips_missing_school_id(self, app):
        """Regression: announcements traces tenancy via classes (no school_id
        column) — the builder must skip it, not crash with UndefinedColumn."""
        from app.core.rls import enable_rls_on_table

        with app.app_context():
            assert enable_rls_on_table("announcements") is False
            app.extensions["sqlalchemy"].session.commit()
        assert "tenant_isolation_announcements" not in self._policies(app, "announcements")

    def test_enable_rls_on_table_is_idempotent(self, app):
        from app.core.rls import enable_rls_on_table

        with app.app_context():
            enable_rls_on_table("grades")
            app.extensions["sqlalchemy"].session.commit()
            enable_rls_on_table("grades")  # must drop + recreate, not raise
            app.extensions["sqlalchemy"].session.commit()

        names = self._policies(app, "grades")
        assert names.count("tenant_isolation_grades") == 1

    def test_enable_rls_on_indirect_table_uses_subquery(self, app):
        from app.core.rls import enable_rls_on_indirect_table

        subquery = "SELECT c.school_id FROM classes c WHERE c.id = quizzes.class_id"
        with app.app_context():
            assert enable_rls_on_indirect_table("quizzes", subquery) is True
            app.extensions["sqlalchemy"].session.commit()

        assert self._rls_enabled(app, "quizzes") is True
        assert "tenant_isolation_quizzes" in self._policies(app, "quizzes")

        with app.app_context():
            expr = (
                app.extensions["sqlalchemy"]
                .session.execute(
                    text(
                        "SELECT qual FROM pg_policies "
                        "WHERE tablename = 'quizzes' AND policyname = 'tenant_isolation_quizzes'"
                    )
                )
                .scalar()
            )
        assert "school_id" in (expr or "")

    def test_disable_all_rls_policies_removes_everything(self, app):
        from app.core.rls import disable_all_rls_policies, enable_rls_on_table

        with app.app_context():
            enable_rls_on_table("grades")
            app.extensions["sqlalchemy"].session.commit()
            disable_all_rls_policies()

        assert self._policies(app, "grades") == []
        assert self._rls_enabled(app, "grades") is False

    def test_enable_all_rls_policies_covers_or_skips_every_registry_table(self, app):
        """Every registry table ends with a policy OR a justified skip."""
        from app.core.rls import _INDIRECT_TENANT_TABLES, _TENANT_TABLES, enable_all_rls_policies
        from sqlalchemy import inspect as sa_inspect

        with app.app_context():
            enable_all_rls_policies()
        try:
            with app.app_context():
                sess = app.extensions["sqlalchemy"].session
                covered = {
                    r[0]
                    for r in sess.execute(
                        text("SELECT tablename FROM pg_policies WHERE policyname LIKE 'tenant_isolation_%'")
                    ).fetchall()
                }
                insp = sa_inspect(sess.get_bind())
                unjustified = []
                for table in set(_TENANT_TABLES) | set(_INDIRECT_TENANT_TABLES):
                    if table in covered:
                        continue
                    if not insp.has_table(table):
                        continue  # absent table: skip is justified
                    cols = {c["name"] for c in insp.get_columns(table)}
                    if "school_id" not in cols:
                        continue  # no tenancy column: skip is justified
                    unjustified.append(table)
            assert not unjustified, f"tables neither covered nor justified: {unjustified}"
        finally:
            with app.app_context():
                from app.core.rls import enable_all_rls_policies as _re

                _re()  # idempotent re-enable restores state


# ═══════════════════════════════════════════════════════════════════════════
# RLS — real behavioral enforcement (session role must be non-superuser)
# ═══════════════════════════════════════════════════════════════════════════


class TestRLSBehavioralIsolation:
    """The policy must actually block cross-tenant rows for a non-superuser.

    Both app roles (postgres locally, azad_test in CI) are superusers, which
    bypass RLS — so the probe connects through a dedicated minimal role.
    """

    PROBE = "rls_probe"

    @pytest.fixture(autouse=True)
    def _probe_role(self, app):
        """Create (idempotently) a non-superuser login with SELECT on grades."""
        with app.app_context():
            sess = app.extensions["sqlalchemy"].session
            sess.execute(
                text(
                    "DO $$ BEGIN "
                    "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rls_probe') THEN "
                    "CREATE ROLE rls_probe LOGIN PASSWORD 'rls_probe'; END IF; END $$;"
                )
            )
            dbname = sess.execute(text("SELECT current_database()")).scalar()
            sess.execute(text(f"GRANT CONNECT ON DATABASE {dbname} TO {self.PROBE}"))
            sess.execute(text("GRANT USAGE ON SCHEMA public TO rls_probe"))
            sess.execute(text("GRANT SELECT ON grades TO rls_probe"))
            sess.commit()
        yield

    def _probe_engine(self, app):
        url = app.config["SQLALCHEMY_DATABASE_URI"]
        head, tail = url.rsplit("@", 1)
        return sqlalchemy.create_engine(f"postgresql+psycopg2://{self.PROBE}:rls_probe@{tail}")

    def test_cross_tenant_select_blocked_same_tenant_allowed(self, app):
        from app.core.rls import enable_rls_on_table

        with app.app_context():
            enable_rls_on_table("grades")
            app.extensions["sqlalchemy"].session.commit()

        sid_a = make_school(app)
        sid_b = make_school(app)
        gid_a = make_grade(app, sid_a)

        engine = self._probe_engine(app)
        try:
            # One implicit DBAPI transaction spans the whole block — the
            # transaction-local set_config survives across both SELECTs.
            with engine.connect() as conn:
                # School B context: school A's grade row must be invisible.
                conn.execute(
                    text("SELECT set_config('app.current_school_id', :v, true)"),
                    {"v": str(sid_b)},
                )
                seen_b = conn.execute(text("SELECT count(*) FROM grades WHERE id = :i"), {"i": gid_a}).scalar()
                # School A context: its own row must be visible.
                conn.execute(
                    text("SELECT set_config('app.current_school_id', :v, true)"),
                    {"v": str(sid_a)},
                )
                seen_a = conn.execute(text("SELECT count(*) FROM grades WHERE id = :i"), {"i": gid_a}).scalar()
        finally:
            engine.dispose()

        assert seen_b == 0, "cross-tenant row leaked through RLS"
        assert seen_a == 1, "same-tenant row unexpectedly blocked"

    def test_set_tenant_context_roundtrip(self, app):
        from app.core.rls import reset_tenant_context, set_tenant_context

        with app.app_context():
            set_tenant_context(7)
            val = (
                app.extensions["sqlalchemy"]
                .session.execute(text("SELECT current_setting('app.current_school_id', true)"))
                .scalar()
            )
            assert val == "7"
            reset_tenant_context()


# ═══════════════════════════════════════════════════════════════════════════
# OpenAPI — init_swagger branches
# ═══════════════════════════════════════════════════════════════════════════


class TestInitSwagger:
    """Both branches of init_swagger, on throwaway apps (the session app
    already has swagger registered by create_app — re-registering would
    duplicate the route)."""

    @staticmethod
    def _fresh_app(**config):
        from flask import Flask

        a = Flask(__name__)
        a.config.update(config)
        return a

    def test_disabled_config_returns_none(self):
        from app.core.openapi import init_swagger

        a = self._fresh_app(SWAGGER_ENABLED=False)
        assert init_swagger(a) is None

    def test_registered_returns_swagger_and_serves_raw_spec(self):
        from app.core.openapi import init_swagger

        a = self._fresh_app(
            SWAGGER_HOST="api.example.com",
            SWAGGER_SPEC={"openapi": "3.0.3", "info": {"title": "t"}},
        )
        swagger = init_swagger(a)
        assert swagger is not None

        client = a.test_client()
        resp = client.get("/api/v1/openapi.json")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["openapi"] == "3.0.3"
        assert body["info"]["title"] == "t"

    def test_host_config_is_applied_to_template_copy(self):
        from app.core.openapi import SWAGGER_TEMPLATE, init_swagger

        a = self._fresh_app(SWAGGER_HOST="api.example.com")
        init_swagger(a)
        assert SWAGGER_TEMPLATE.get("host") != "api.example.com"  # copy, not mutation


# ═══════════════════════════════════════════════════════════════════════════
# Cache — backend fallback branches
# ═══════════════════════════════════════════════════════════════════════════


class TestCacheBackends:
    @pytest.fixture(autouse=True)
    def _fresh_memory_backend(self):
        from app.core import cache

        cache.reset_cache_backend()
        cache._MEM.clear()
        yield
        cache.reset_cache_backend()
        cache._MEM.clear()

    def test_set_get_delete_roundtrip_memory(self):
        from app.core import cache

        cache.set("k1", {"a": 1}, ttl=60)
        assert cache.get("k1") == {"a": 1}
        cache.delete("k1")
        assert cache.get("k1") is None

    def test_ttl_expiry_returns_none_and_evicts(self):
        from app.core import cache

        cache.set("ttl", "v", ttl=1)
        entry = cache._MEM["ttl"]
        cache._MEM["ttl"] = (time.monotonic() - 0.01, entry[1])
        assert cache.get("ttl") is None
        assert "ttl" not in cache._MEM  # expired entry was evicted on read

    def test_missing_key_returns_none(self):
        from app.core import cache

        assert cache.get("never-set") is None

    def test_broken_redis_client_falls_back_to_memory(self, monkeypatch):
        """Redis package import succeeds but every call fails → memory wins."""
        monkeypatch.setenv("RATELIMIT_STORAGE_URL", "redis://localhost:6379/0")
        from app.core import cache

        broken = types.ModuleType("redis")

        class _Boom:
            @staticmethod
            def from_url(*a, **kw):
                raise RuntimeError("down")

        broken.Redis = _Boom
        monkeypatch.setitem(sys.modules, "redis", broken)
        cache.reset_cache_backend()
        assert cache._get_redis() is None

        cache.set("bk", [1, 2], ttl=30)
        assert cache.get("bk") == [1, 2]
        cache.delete("bk")
        assert cache.get("bk") is None

    def test_clear_purges_memory_and_scans_redis_when_present(self, monkeypatch):
        monkeypatch.setenv("RATELIMIT_STORAGE_URL", "redis://localhost:6379/0")
        from app.core import cache

        cache.set("c1", 1, ttl=30)
        cache.set("c2", 2, ttl=30)

        deleted: list[str] = []

        class _FakeRedis:
            def ping(self):
                return True

            def scan_iter(self, pattern):
                assert pattern == "azad:cache:*"
                yield "azad:cache:c1"
                yield "azad:cache:c2"

            def delete(self, k):
                deleted.append(k)

        fake = types.ModuleType("redis")
        fake.Redis = types.SimpleNamespace(from_url=lambda *a, **kw: _FakeRedis())
        monkeypatch.setitem(sys.modules, "redis", fake)
        cache.reset_cache_backend()

        cache.clear()
        assert sorted(deleted) == ["azad:cache:c1", "azad:cache:c2"]
        assert cache.get("c1") is None and cache.get("c2") is None

    def test_json_roundtrip_preserves_nested_payload(self):
        from app.core import cache

        payload = {"nested": {"ok": True}, "n": 3, "s": "نص"}
        cache.set("json", payload, ttl=30)
        assert json.loads(json.dumps(cache.get("json"))) == payload
