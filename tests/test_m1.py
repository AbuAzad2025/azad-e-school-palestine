"""م1 — المصادقة، القواميس (i18n)، الذرّية، والتينانتس المركزي"""
import uuid

import pytest

from app import create_app
from app.core.db import tx
from app.core.security import hash_password, verify_password
from app.core.tenancy import scope_by_school
from app.extensions import db
from app.models.user import User, UserRole

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
        data={"name_ar": "طالب تجربة", "email": email, "role": role, "password": "secret123", "confirm": "secret123"},
        follow_redirects=True,
    )
    return r, email


def test_hash_and_verify_password():
    hashed = hash_password("s3cret!")
    assert hashed != "s3cret!"
    assert verify_password(hashed, "s3cret!")
    assert not verify_password(hashed, "wrong")


def test_register_flow_and_confirm(app, client):
    r, email = _register(client)
    assert r.status_code == 200
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        assert user is not None
        assert not user.is_verified
        assert user.role == UserRole.student
        uid = user.id
    # تفعيل البريد عبر رابط مؤمن
    with app.app_context():
        from app.core import make_activation_token

        token = make_activation_token(uid, email)
    r = client.get(f"/auth/confirm/{token}", follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        assert db.session.get(User, uid).is_verified


def test_login_without_verification_blocked(app, client):
    _, email = _register(client)
    r = client.post(
        "/auth/login",
        data={"email": email, "password": "secret123"},
        follow_redirects=True,
    )
    body = r.get_data(as_text=True)
    assert "فعّل بريدك الإلكتروني أولاً" in body


def test_full_login_dashboard(app, client):
    _, email = _register(client)
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        user.is_verified = True
        db.session.commit()
    r = client.post(
        "/auth/login",
        data={"email": email, "password": "secret123"},
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
            db.session.add(
                User(email="n@example.com", name_ar="ن", role=UserRole.student, password_hash="h")
            )
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
        assert ids == {g1.id, g2.id}, "نطاق التينانتس لم يَعزل المدرسة الأولى"
        assert g3.id not in ids, "تسرّب من المدرسة الثانية!"


def test_tenancy_scope_rejects_model_without_school(app):
    from app.models.school import School

    with app.app_context():
        with pytest.raises(ValueError):
            scope_by_school(School, 1)
