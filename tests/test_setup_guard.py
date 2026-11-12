"""حراسة الإعداد الأولي: ذاكرة وجود مالك المنصة + صفحة ``/auth/setup``.

الحالة التي تحميها هذه الاختبارات هي أخطر ما يواجه أول نشر: لا يوجد مالك
منصة بعد، فيجب أن يُحوَّل كل زائر إلى معالج الإعداد. الخطر ليس غياب التحويل،
بل أن يبقى التحويل إلى الأبد *بعد* إنشاء المالك: العامل الذي خدم
``POST /auth/setup`` كان يحتفظ بإجابة قديمة «لا مالك» فيعيد توجيه
``/auth/login`` إلى المعالج، بينما المعالج يرى المالك الجديد فيعيد التوجيه
إلى ``/auth/login`` — حلقة لا نهائية تُقفل المنصة أمام الجميع.

لذلك نثبت هنا:
  * تُخزَّن الإجابة الإيجابية فقط، والسلبية تُعاد قراءتها من قاعدة البيانات،
  * بعد نجاح إنشاء المالك ينتهي التحويل فوراً على نفس العامل،
  * ``/auth/setup`` و``/health`` مستثنيان من التحويل،
  * فشل الاستعلام (جداول لم تُرحَّل بعد) لا يحجب المنصة،
  * رفض المدخلات الناقصة وفشل المعاملة لا يُنشئان مالكاً.
"""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from app.core.security import hash_password
from app.extensions import db
from app.models.user import User, UserApprovalStatus, UserRole

VALID_OWNER = {
    "email": "owner@azad.test",
    "password": "OwnerPass123!",
    "name_ar": "مالك المنصة",
    "name_en": "Platform Owner",
}


def _drop_cache(app) -> None:
    """يمسح ذاكرة العامل — الحالة تُخزَّن على كائن التطبيق لا على config."""
    app.__dict__.pop("_has_super_admin", None)


@pytest.fixture(autouse=True)
def _isolated_guard_cache(app):
    """الذاكرة تعيش على كائن session-scoped، فتُنظَّف قبل وبعد كل اختبار."""
    _drop_cache(app)
    yield
    _drop_cache(app)


def _as_production(app) -> None:
    """يشغّل الحراسة كما في الإنتاج (``TESTING`` يعطّلها عمداً)."""
    app.config["TESTING"] = False
    app.config["SETUP_REDIRECT_ENABLED"] = True


def _create_super_admin(app) -> int:
    with app.app_context():
        owner = User(
            email=f"owner-{uuid4().hex[:8]}@azad.test",
            name_ar="مالك المنصة",
            role=UserRole.super_admin,
            password_hash=hash_password("OwnerPass123!"),
            approval_status=UserApprovalStatus.approved,
            is_active=True,
            is_verified=True,
        )
        db.session.add(owner)
        db.session.commit()
        return owner.id


def _super_admin_count(app) -> int:
    with app.app_context():
        return db.session.query(User).filter(User.role == UserRole.super_admin).count()


def _boom(*_args, **_kwargs):
    raise RuntimeError('relation "users" does not exist')


def _break_db(monkeypatch) -> None:
    """يجعل ``from app.extensions import db`` يعيد كائناً يفشل عند أول استعلام."""
    monkeypatch.setattr("app.extensions.db", SimpleNamespace(session=SimpleNamespace(execute=_boom)))


class TestSetupGuard:
    def test_redirects_to_wizard_when_no_owner(self, app, client):
        _as_production(app)

        response = client.get("/auth/login")

        assert response.status_code == 302
        assert urlparse(response.headers["Location"]).path == "/auth/setup"
        # الإجابة السلبية لا تُخزَّن: وإلا بقي العامل على «لا مالك» بعد الإعداد.
        assert "_has_super_admin" not in app.__dict__

    def test_setup_and_health_paths_are_exempt(self, app, client):
        _as_production(app)

        assert client.get("/auth/setup").status_code == 200
        assert client.get("/health").status_code == 200

    def test_existing_owner_is_served_and_answer_is_cached(self, app, client):
        _create_super_admin(app)
        _as_production(app)

        response = client.get("/auth/login")

        assert response.status_code == 200
        assert app.__dict__["_has_super_admin"] is True

    def test_cached_positive_answer_skips_further_queries(self, app, client, monkeypatch):
        _create_super_admin(app)
        _as_production(app)
        assert client.get("/auth/login").status_code == 200

        # الذاكرة الإيجابية تعني صفر استعلامات في المسار الساخن.
        _break_db(monkeypatch)

        assert client.get("/auth/login").status_code == 200

    def test_query_failure_does_not_block_the_platform(self, app, client, monkeypatch):
        _as_production(app)
        _break_db(monkeypatch)

        # جداول لم تُرحَّل بعد: نتجاهل الحراسة بدل إسقاط كل طلب بـ500.
        assert client.get("/auth/login").status_code == 200


class TestSetupWizard:
    def test_creates_owner_and_ends_the_redirect_loop(self, app, client):
        _as_production(app)
        before = client.get("/auth/login")
        assert before.status_code == 302
        assert urlparse(before.headers["Location"]).path == "/auth/setup"

        response = client.post("/auth/setup", data=VALID_OWNER)

        assert response.status_code == 302
        assert urlparse(response.headers["Location"]).path == "/auth/login"
        assert _super_admin_count(app) == 1
        # الانحدار الذي نحميه: نفس العملية تخدم صفحة الدخول الآن، ولا حلقة.
        assert client.get("/auth/login").status_code == 200
        assert client.get("/auth/setup").status_code == 302

    def test_redirects_to_login_once_owner_exists(self, app, client):
        _create_super_admin(app)
        _as_production(app)

        response = client.get("/auth/setup")

        assert response.status_code == 302
        assert urlparse(response.headers["Location"]).path == "/auth/login"

    def test_rejects_incomplete_input_without_creating_owner(self, app, client):
        _as_production(app)

        response = client.post("/auth/setup", data={})

        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert "البريد الإلكتروني مطلوب." in body
        assert "الاسم (عربي) مطلوب." in body
        assert _super_admin_count(app) == 0

    def test_transaction_failure_does_not_create_owner(self, app, client, monkeypatch):
        _as_production(app)

        def _broken_tx(*_args, **_kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr("app.core.db.tx", _broken_tx)

        response = client.post("/auth/setup", data=VALID_OWNER)

        assert response.status_code == 200
        assert _super_admin_count(app) == 0
