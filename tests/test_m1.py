"""م1 — المصادقة، القواميس (i18n)، الذرّية، والتينانتس المركزي"""

import uuid

import pytest
from app import create_app
from app.core.db import tx
from app.core.security import hash_password, verify_password
from app.core.tenancy import scope_by_school
from app.extensions import db
from app.models.user import User, UserApprovalStatus, UserRole


@pytest.fixture()
def app():
    a = create_app()
    a.config["TESTING"] = True
    a.config["WTF_CSRF_ENABLED"] = False
    with a.app_context():
        db.create_all()  # لا drop_all — القاعدة حية ولا تُهدم (اختبارات schema تعتمد عليها)
    yield a


@pytest.fixture()
def client(app):
    return app.test_client()


def _new_email():
    return f"u-{uuid.uuid4().hex[:10]}@example.com"


def _register(client, email=None, role="student"):
    email = email or _new_email()
    r = client.post(
        "/auth/register",
        data={"name_ar": "طالب تجربة", "email": email, "role": role, "password": "Secret123!", "confirm": "Secret123!"},
        follow_redirects=True,
    )
    return r, email


def test_hash_and_verify_password():
    hashed = hash_password("s3cret!")
    assert hashed != "s3cret!"
    assert verify_password(hashed, "s3cret!")
    assert not verify_password(hashed, "wrong")


def test_register_creates_pending_user(app, client):
    """اختبار أن التسجيل ينشئ مستخدم بحالة pending."""
    r, email = _register(client)
    assert r.status_code == 200
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        assert user is not None
        assert user.approval_status == UserApprovalStatus.pending
        assert user.is_verified == False  # لم يعد مطلوباً
        assert user.role == UserRole.student


def test_login_pending_user_blocked(app, client):
    """اختبار أن المستخدم بحالة pending لا يستطيع تسجيل الدخول."""
    _, email = _register(client)
    r = client.post(
        "/auth/login",
        data={"email": email, "password": "Secret123!"},
        follow_redirects=True,
    )
    body = r.get_data(as_text=True)
    assert "في انتظار موافقة الإدارة" in body


def test_admin_can_approve_user(app, client):
    """اختبار أن السوبر أدمن يمكنه قبول المستخدم."""
    _, email = _register(client)
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        assert user.approval_status == UserApprovalStatus.pending

        # محاكاة موافقة السوبر أدمن
        user.approval_status = UserApprovalStatus.approved
        db.session.commit()

        # الآن المستخدم يستطيع تسجيل الدخول
        user = User.query.filter_by(email=email).first()
        assert user.approval_status == UserApprovalStatus.approved
        assert user.is_approved == True


def test_admin_can_reject_user(app, client):
    """اختبار أن السوبر أدمن يمكنه رفض المستخدم."""
    _, email = _register(client)
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        user.approval_status = UserApprovalStatus.rejected
        db.session.commit()

        user = User.query.filter_by(email=email).first()
        assert user.approval_status == UserApprovalStatus.rejected
        assert user.is_approved == False


def test_rejected_user_cannot_login(app, client):
    """اختبار أن المستخدم المرفوض لا يستطيع تسجيل الدخول."""
    _, email = _register(client)
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        user.approval_status = UserApprovalStatus.rejected
        db.session.commit()

    r = client.post(
        "/auth/login",
        data={"email": email, "password": "Secret123!"},
        follow_redirects=True,
    )
    body = r.get_data(as_text=True)
    assert "في انتظار موافقة الإدارة" in body or "مرفوض" in body


def test_full_login_after_approval(app, client):
    """اختبار تسجيل الدخول الكامل بعد الموافقة."""
    _, email = _register(client)
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        user.approval_status = UserApprovalStatus.approved
        db.session.commit()

    r = client.post(
        "/auth/login",
        data={"email": email, "password": "Secret123!"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "لوحتي" in r.get_data(as_text=True)


def test_duplicate_email_rejected(app, client):
    _, email = _register(client)
    r, _ = _register(client, email=email)
    assert "هذا البريد مسجّل مسبقاً" in r.get_data(as_text=True)


def test_i18n_en_catalog_renders(client):
    client.set_cookie("locale", "en")
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert 'lang="en"' in html
    assert 'dir="ltr"' in html
    assert "Azad Electronic School" in html


def test_i18n_default_arabic_rtl(client):
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert 'lang="ar"' in html
    assert 'dir="rtl"' in html
    assert "مدرسة أزاد الإلكترونية" in html


def test_locale_switch_route(client):
    r = client.post("/set-locale/en")
    assert r.status_code == 302
    assert "locale=en" in r.headers.get("Set-Cookie", "")
    r = client.post("/set-locale/xx")
    assert r.status_code == 302
    assert "locale=ar" in r.headers.get("Set-Cookie", "")


def test_tx_rolls_back_on_error(app):
    with app.app_context():
        user = User(
            email=f"atomic-{uuid.uuid4().hex[:8]}@example.com",
            name_ar="ذرّية",
            role=UserRole.student,
            password_hash=hash_password("x"),
        )
        db.session.add(user)
        db.session.commit()
        count_before = User.query.count()

        # خدمة ترفع خطأً في منتصف الكتابة — يجب التراجع كاملاً
        def _boom():
            db.session.add(User(email="n@example.com", name_ar="ن", role=UserRole.student, password_hash="h"))
            raise RuntimeError("فشل مقصود")

        with pytest.raises(RuntimeError):
            tx(_boom)
        assert User.query.count() == count_before, "المعاملة لم تُتراجع ذرّياً"


def test_tenancy_scope_filters_by_school(app):
    from app.models.school import Grade, School

    with app.app_context():
        s1 = School(name_ar="مدرسة أ", name_en="School A", domain=f"a-{uuid.uuid4().hex[:8]}.example.org")
        s2 = School(name_ar="مدرسة ب", name_en="School B", domain=f"b-{uuid.uuid4().hex[:8]}.example.org")
        db.session.add_all([s1, s2])
        db.session.commit()
        g1 = Grade(school_id=s1.id, grade_level=1)
        g2 = Grade(school_id=s1.id, grade_level=2)
        g3 = Grade(school_id=s2.id, grade_level=1)
        db.session.add_all([g1, g2, g3])
        db.session.commit()
        rows = scope_by_school(Grade, s1.id).all()
        ids = {r.id for r in rows}
        assert ids == {g1.id, g2.id}, "نطاق التينانتس لم يعزل المدرسة الأولى"
        assert g3.id not in ids, "تسرّب من المدرسة الثانية!"


def test_tenancy_scope_rejects_model_without_school(app):
    from app.models.school import School

    with app.app_context():
        with pytest.raises(ValueError):
            scope_by_school(School, 1)


def test_password_reset_flow(app, client):
    from app.core import make_reset_token

    _, email = _register(client)
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        assert user is not None
        user.approval_status = UserApprovalStatus.approved
        db.session.commit()
        token = make_reset_token(user.id, email)
    r = client.post(
        f"/auth/reset/{token}",
        data={"password": "NewPass123!", "confirm": "NewPass123!"},
        follow_redirects=True,
    )
    assert "تم تحديث كلمة المرور" in r.get_data(as_text=True)
    with app.app_context():
        assert verify_password(db.session.get(User, user.id).password_hash, "NewPass123!")
        assert not verify_password(db.session.get(User, user.id).password_hash, "Secret123!")


def test_password_reset_bad_token_rejected(app, client):
    _, email = _register(client)
    r = client.post(
        "/auth/reset/forged-token",
        data={"password": "NewPass123!", "confirm": "NewPass123!"},
        follow_redirects=True,
    )
    assert "غير صالح أو منتهي" in r.get_data(as_text=True)
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        assert verify_password(user.password_hash, "Secret123!")


def test_forgot_route_prints_reset_link(app, client):
    _, email = _register(client)
    r = client.post("/auth/forgot", data={"email": email}, follow_redirects=True)
    assert "إن كان البريد مسجلاً" in r.get_data(as_text=True)
