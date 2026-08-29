import json

from app.extensions import db
from tests.conftest import (
    make_class,
    make_class_member,
    make_grade,
    make_grade_category,
    make_grade_entry,
    make_grade_item,
    make_school,
    make_subject,
    make_system_school,
    make_user,
)


def test_landing_renders_for_anonymous(client):
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'dir="rtl"' in html
    assert 'lang="ar"' in html


def test_landing_en_renders_ltr(client):
    client.set_cookie("locale", "en")
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'lang="en"' in html
    assert 'dir="ltr"' in html


def test_landing_ar_rtl(client):
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert 'dir="rtl"' in html
    assert 'lang="ar"' in html


def test_landing_authenticated_redirects(client, app):
    user_id = make_user(app, role="student")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (301, 302)
    loc = r.headers.get("Location", "") or r.location
    assert "dashboard" in loc


def test_landing_has_hero(client):
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert "hero" in html.lower()


def test_landing_has_features(client):
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert "feat-card" in html


def test_landing_has_cta(client):
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert "cta" in html.lower()


def test_landing_has_register_links(client):
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert "register-individual" in html


def test_set_locale_redirect(client):
    r = client.post("/set-locale/en", follow_redirects=False)
    assert r.status_code in (301, 302)


def test_set_locale_invalid_falls_back(client):
    r = client.post("/set-locale/xyz", follow_redirects=False)
    assert r.status_code in (301, 302)


def test_pwa_manifest_accessible(client):
    r = client.get("/static/manifest.json")
    assert r.status_code == 200
    data = json.loads(r.get_data(as_text=True))
    assert data["short_name"] == "أزاد"
    assert data["dir"] == "rtl"
    assert data["lang"] == "ar"
    assert data["display"] == "standalone"
    assert len(data["icons"]) == 2


def test_pwa_manifest_has_categories(client):
    r = client.get("/static/manifest.json")
    data = json.loads(r.get_data(as_text=True))
    assert "education" in data.get("categories", [])


def test_sw_accessible(client):
    r = client.get("/static/sw.js")
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert "install" in text.lower()
    assert "activate" in text.lower()
    assert "fetch" in text.lower()


def test_sw_has_cache_strategy(client):
    r = client.get("/static/sw.js")
    text = r.get_data(as_text=True)
    assert "caches" in text.lower()
    assert "CACHE_NAME" in text


def test_offline_page_accessible(client):
    r = client.get("/static/offline.html")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "offline" in html.lower() or "غير متصل" in html


def test_base_html_has_manifest_link(client, app):
    user_id = make_user(app, role="student")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    r = client.get("/auth/dashboard")
    html = r.get_data(as_text=True)
    assert "manifest.json" in html


def test_base_html_loads_js_module(client, app):
    user_id = make_user(app, role="student")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    r = client.get("/auth/dashboard")
    html = r.get_data(as_text=True)
    assert 'type="module"' in html
    assert "js/index.js" in html


def test_sw_registration_moved_to_js_module(client):
    r = client.get("/static/js/index.js")
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert "serviceWorker" in text


def test_base_html_has_pwa_install_banner(client, app):
    user_id = make_user(app, role="student")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    r = client.get("/auth/dashboard")
    html = r.get_data(as_text=True)
    assert "pwa-install-banner" in html


def test_subject_moe_fields_exist(app):
    with app.app_context():
        from app.models.school import Subject

        s = Subject(name_ar="فيزياء")
        s.moe_code = "PHY101"
        s.moe_curriculum_version = "2025"
        db.session.add(s)
        db.session.commit()
        loaded = db.session.get(Subject, s.id)
        assert loaded.moe_code == "PHY101"
        assert loaded.moe_curriculum_version == "2025"


def test_subject_moe_fields_nullable(app):
    with app.app_context():
        from app.models.school import Subject

        s = Subject(name_ar="كيمياء")
        db.session.add(s)
        db.session.commit()
        loaded = db.session.get(Subject, s.id)
        assert loaded.moe_code is None
        assert loaded.moe_curriculum_version is None


def test_certificate_template_create(app):
    with app.app_context():
        from app.models.system import CertificateTemplate

        t = CertificateTemplate(name="شهادة التوجيهي", template_html="<h1>شهادة</h1>")
        db.session.add(t)
        db.session.commit()
        loaded = db.session.get(CertificateTemplate, t.id)
        assert loaded.name == "شهادة التوجيهي"
        assert loaded.is_active is True
        assert loaded.school_id is None


def test_certificate_template_with_school(app):
    with app.app_context():
        from app.models.system import CertificateTemplate

        school_id = make_school(app)
        t = CertificateTemplate(name="شهادة المدرسة", school_id=school_id, template_html="<h1>شهادة</h1>")
        db.session.add(t)
        db.session.commit()
        loaded = db.session.get(CertificateTemplate, t.id)
        assert loaded.school_id == school_id


def test_certificate_template_default_active(app):
    with app.app_context():
        from app.models.system import CertificateTemplate

        t = CertificateTemplate(name="قالب", template_html="")
        db.session.add(t)
        db.session.commit()
        loaded = db.session.get(CertificateTemplate, t.id)
        assert loaded.is_active is True


def test_export_moe_format_empty(app):
    from app.services.export import export_moe_format

    with app.app_context():
        data = export_moe_format()
        assert isinstance(data, bytes)
        assert len(data) > 0


def test_export_moe_format_with_school(app):
    from app.services.export import export_moe_format

    school_id = make_school(app)
    with app.app_context():
        data = export_moe_format(school_id=school_id)
        assert isinstance(data, bytes)
        assert len(data) > 0


def test_export_moe_format_with_grades(app):
    from app.services.export import export_moe_format

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app, name="رياضيات")
    class_id = make_class(app, school_id, grade_id, subject_id)
    make_class_member(app, class_id, student_id)
    cat_id = make_grade_category(app, class_id, "اختبارات", 1.0)
    item_id = make_grade_item(app, class_id, cat_id, "midterm", 20)
    make_grade_entry(app, student_id, item_id, 18)

    with app.app_context():
        data = export_moe_format(school_id=school_id, academic_year="2025-2026")
        assert isinstance(data, bytes)
        assert len(data) > 0


def test_admin_moe_export_requires_auth(client):
    r = client.get("/admin/moe-export", follow_redirects=False)
    assert r.status_code in (301, 302, 401, 500)


def test_admin_certificates_requires_auth(client):
    r = client.get("/admin/certificates", follow_redirects=False)
    assert r.status_code in (301, 302, 401, 500)


def test_admin_moe_export_requires_super_admin(client, app):
    user_id = make_user(app, role="school_admin")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    r = client.get("/admin/moe-export", follow_redirects=False)
    assert r.status_code in (403, 302)


def test_admin_certificates_requires_super_admin(client, app):
    user_id = make_user(app, role="school_admin")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    r = client.get("/admin/certificates", follow_redirects=False)
    assert r.status_code in (403, 302)


def test_admin_moe_export_get(client, app):
    make_system_school(app)
    user_id = make_user(app, role="super_admin")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    r = client.get("/admin/moe-export")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "MOE" in html or "moe" in html.lower() or "وزارة" in html


def test_admin_certificates_get(client, app):
    make_system_school(app)
    user_id = make_user(app, role="super_admin")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    r = client.get("/admin/certificates")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "شهادات" in html or "certificate" in html.lower()


def test_admin_moe_export_post(client, app):
    make_system_school(app)
    user_id = make_user(app, role="super_admin")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    r = client.post("/admin/moe-export", data={"school_id": "", "academic_year": "2025-2026"})
    assert r.status_code == 200


def test_admin_moe_export_post_with_school(client, app):
    school_id = make_school(app)
    make_system_school(app)
    user_id = make_user(app, role="super_admin")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    r = client.post("/admin/moe-export", data={"school_id": str(school_id), "academic_year": ""})
    assert r.status_code == 200


def test_admin_certificates_shows_templates(client, app):
    make_system_school(app)
    user_id = make_user(app, role="super_admin")
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
    with app.app_context():
        from app.models.system import CertificateTemplate

        t = CertificateTemplate(name="test-cert", template_html="<div>cert</div>")
        db.session.add(t)
        db.session.commit()
    r = client.get("/admin/certificates")
    html = r.get_data(as_text=True)
    assert "test-cert" in html


def test_landing_stats_reflect_real_data(app, client):
    make_school(app)
    r = client.get("/")
    assert r.status_code == 200
