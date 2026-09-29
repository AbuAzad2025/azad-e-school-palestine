"""تغطية فجوات app/core — bootstrap، api_tenancy (فرع المعلم)، pdf، labels.

كل اختبار يمر بمسارات حقيقية: تهيئة النظام على قاعدة الاختبار، استعلامات
نطاق حقيقية، وتوليد PDF فعلي — بدون اختبارات شكلية.
"""

from unittest.mock import patch

from tests.conftest import make_class, make_class_member, make_grade, make_lesson, make_school, make_subject, make_user

# ═══════════════════════════════════════════════════════════════════════
# app/core/bootstrap.py — كان 0%: كيانات النظام + التقرير + idempotency
# ═══════════════════════════════════════════════════════════════════════


class TestBootstrap:
    def test_ensure_system_school_exists_creates_and_returns(self, app):
        from app.core.bootstrap import ensure_system_school_exists
        from app.models.school import School
        from app.services.schools import SYSTEM_SCHOOL_DOMAIN

        with app.app_context():
            school = ensure_system_school_exists()
            assert school.id is not None
            assert school.domain == SYSTEM_SCHOOL_DOMAIN
            # موجود فعلياً في قاعدة البيانات
            assert School.query.get(school.id) is not None

    def test_ensure_system_school_exists_idempotent(self, app):
        from app.core.bootstrap import ensure_system_school_exists

        with app.app_context():
            first = ensure_system_school_exists()
            second = ensure_system_school_exists()
            assert first.id == second.id

    def test_ensure_super_admin_exists_creates_with_hashed_password(self, app):
        from app.core.bootstrap import ensure_super_admin_exists
        from app.core.security import verify_password
        from app.models.user import User, UserRole

        with app.app_context():
            user = ensure_super_admin_exists("bootstrap-admin@test.com", "Sup3rSecret!")
            assert user.role == UserRole.super_admin
            assert verify_password(user.password_hash, "Sup3rSecret!")
            assert User.query.get(user.id) is not None

    def test_ensure_super_admin_exists_returns_existing(self, app):
        from app.core.bootstrap import ensure_super_admin_exists

        with app.app_context():
            first = ensure_super_admin_exists("bootstrap-admin2@test.com", "FirstPass1!")
            second = ensure_super_admin_exists("bootstrap-admin2@test.com", "OtherPass2!")
            assert first.id == second.id

    def test_bootstrap_system_report_without_admin(self, app):
        from app.core.bootstrap import bootstrap_system
        from app.services.schools import SYSTEM_SCHOOL_DOMAIN

        with app.app_context():
            report = bootstrap_system(app)
            assert report["system_school"]["exists"] is True
            assert report["system_school"]["domain"] == SYSTEM_SCHOOL_DOMAIN
            assert report["system_school"]["id"] is not None
            assert report["super_admin"] is None

    def test_bootstrap_system_report_with_admin(self, app):
        from app.core.bootstrap import bootstrap_system

        with app.app_context():
            report = bootstrap_system(app, super_admin_email="bs-admin3@test.com", super_admin_password="Adm1nPass!")
            assert report["super_admin"] is not None
            assert report["super_admin"]["email"] == "bs-admin3@test.com"
            assert report["super_admin"]["exists"] is True

    def test_bootstrap_system_idempotent(self, app):
        from app.core.bootstrap import bootstrap_system

        with app.app_context():
            r1 = bootstrap_system(app, super_admin_email="bs-admin4@test.com", super_admin_password="Adm1nPass!")
            r2 = bootstrap_system(app, super_admin_email="bs-admin4@test.com", super_admin_password="Adm1nPass!")
            assert r1["system_school"]["id"] == r2["system_school"]["id"]
            assert r1["super_admin"]["id"] == r2["super_admin"]["id"]


# ═══════════════════════════════════════════════════════════════════════
# app/core/api_tenancy.py — فرع المعلم في lesson_access_query + الفروع المبكرة
# ═══════════════════════════════════════════════════════════════════════


class TestApiTenancyGaps:
    def test_current_user_school_id_super_admin_returns_none(self, client, app):
        from app.core.api_tenancy import current_user_school_id
        from app.models.user import User
        from flask_login import login_user

        uid = make_user(app, role="super_admin")
        with app.test_request_context():
            with app.app_context():
                user = User.query.get(uid)
                login_user(user)
                assert current_user_school_id() is None

    def test_current_user_school_id_anonymous_returns_none(self, app):
        from app.core.api_tenancy import current_user_school_id

        with app.test_request_context():
            assert current_user_school_id() is None

    def test_accessible_school_ids_anonymous_empty(self, app):
        from app.core.api_tenancy import accessible_school_ids_for_user

        with app.test_request_context():
            assert accessible_school_ids_for_user() == set()

    def test_accessible_school_ids_super_admin_empty(self, client, app):
        from app.core.api_tenancy import accessible_school_ids_for_user
        from app.models.user import User
        from flask_login import login_user

        uid = make_user(app, role="super_admin")
        with app.test_request_context():
            with app.app_context():
                login_user(User.query.get(uid))
                assert accessible_school_ids_for_user() == set()

    def test_teacher_lesson_scope_includes_taught_classes(self, client, app):
        """المعلم يرى دروس الصفوف التي يُدرّسها حتى لو لم يكن عضواً فيها."""
        from app.core.api_tenancy import lesson_access_query_for_current_user
        from app.extensions import db
        from app.models.user import User
        from flask_login import login_user

        sid = make_school(app)
        gid = make_grade(app, sid)
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        lid = make_lesson(app, cid)
        teacher_id = make_user(app, role="teacher", school_id=sid)
        with app.app_context():
            from app.models.class_room import ClassRoom

            ClassRoom.query.get(cid).teacher_id = teacher_id
            db.session.commit()

        with app.test_request_context():
            with app.app_context():
                login_user(User.query.get(teacher_id))
                ids = {lesson.id for lesson in lesson_access_query_for_current_user().all()}
                assert lid in ids

    def test_teacher_lesson_scope_includes_enrolled_classes(self, client, app):
        """المعلم عضواً نشطاً في صف (بلا teacher_id) يرى دروسه أيضاً."""
        from app.core.api_tenancy import lesson_access_query_for_current_user
        from app.models.user import User
        from flask_login import login_user

        sid = make_school(app)
        gid = make_grade(app, sid)
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        lid = make_lesson(app, cid)
        teacher_id = make_user(app, role="teacher", school_id=sid)
        make_class_member(app, cid, teacher_id, status="active")

        with app.test_request_context():
            with app.app_context():
                login_user(User.query.get(teacher_id))
                ids = {lesson.id for lesson in lesson_access_query_for_current_user().all()}
                assert lid in ids

    def test_teacher_lesson_scope_excludes_other_classes(self, client, app):
        from app.core.api_tenancy import lesson_access_query_for_current_user
        from app.models.user import User
        from flask_login import login_user

        sid = make_school(app)
        gid = make_grade(app, sid)
        subj = make_subject(app)
        cid = make_class(app, sid, gid, subj)
        lid = make_lesson(app, cid)
        other_teacher_id = make_user(app, role="teacher", school_id=sid)

        with app.test_request_context():
            with app.app_context():
                login_user(User.query.get(other_teacher_id))
                ids = {lesson.id for lesson in lesson_access_query_for_current_user().all()}
                assert lid not in ids


# ═══════════════════════════════════════════════════════════════════════
# app/core/pdf.py — مسارات الخط الهامشية
# ═══════════════════════════════════════════════════════════════════════


class TestPdfFontPaths:
    def test_iter_font_dirs_windows_branch(self, app):
        from app.core import pdf

        with patch.object(pdf.os, "name", "nt"):
            dirs = pdf._iter_font_dirs()
        assert r"C:\Windows\Fonts" in dirs

    def test_iter_font_dirs_without_app_context(self):
        from app.core import pdf

        # بلا سياق تطبيق: لا Runtime Error — المسار المحمي 70
        dirs = pdf._iter_font_dirs()
        assert isinstance(dirs, list)

    def test_find_font_file_skips_missing_dirs_and_oserror(self, tmp_path):
        from app.core import pdf

        missing = tmp_path / "nope"
        unwritable = tmp_path / "bad"
        unwritable.mkdir()
        with (
            patch.object(pdf, "_DIRS_EXTRA", [str(missing), str(unwritable), str(tmp_path)]),
            patch.object(pdf.os, "name", "posix"),
        ):
            # مجلد موجود بلا خطوط → None
            assert pdf._find_font_file() is None

    def test_find_font_file_finds_lowercase_candidate(self, tmp_path):
        from app.core import pdf

        font_file = tmp_path / pdf._ARABIC_FONT_CANDIDATES[0]
        font_file.write_bytes(b"fake ttf")
        with patch.object(pdf, "_DIRS_EXTRA", [str(tmp_path)]), patch.object(pdf.os, "name", "posix"):
            found = pdf._find_font_file()
        assert found is not None and found.endswith(".ttf")

    def test_font_readiness_warning_when_no_font(self, tmp_path):
        from app.core import pdf

        with patch.object(pdf, "_DIRS_EXTRA", [str(tmp_path)]), patch.object(pdf.os, "name", "posix"):
            report = pdf.font_readiness()
        assert report["status"] == "warning"
        assert report["font_file"] is None
        assert "PDF_FONT_DIR" in report["hint"]

    def test_register_arabic_font_fallback_on_broken_font(self, tmp_path):
        from app.core import pdf

        font_file = tmp_path / pdf._ARABIC_FONT_CANDIDATES[0]
        font_file.write_bytes(b"not a real font")
        with (
            patch.object(pdf, "_DIRS_EXTRA", [str(tmp_path)]),
            patch.object(pdf.os, "name", "posix"),
            patch.object(pdf, "_font_cache", {}),
        ):
            name = pdf.register_arabic_font()
            assert name == pdf._FALLBACK_FONT
            assert pdf._font_cache  # خُزّن مؤقتاً داخل نفس المرجع المُستبدل

    def test_ctx_school_id_without_request(self):
        from app.core.pdf import ctx_school_id

        # لا سياق طلب → 0 (الفرع المحمي 197-199)
        assert ctx_school_id() == 0


# ═══════════════════════════════════════════════════════════════════════
# app/core/labels.py — القيم المعروفة وغير المعروفة
# ═══════════════════════════════════════════════════════════════════════


class TestStatusLabel:
    def test_known_label_inside_request_context(self, client, app):
        from app.core.labels import status_label

        with app.test_request_context(headers={"Accept-Language": "ar"}):
            assert status_label("subscription_status", "active") == "نشط"

    def test_enum_value_unwrapped(self):
        from app.core.labels import status_label
        from app.models.user import UserRole

        # خارج سياق الطلب تُعاد القيمة الخام (الـ msgid عربي لكن بلا لغة محددة)
        assert status_label("role", UserRole.student) in {"طالب", "student"}

    def test_unknown_value_returns_raw(self):
        from app.core.labels import status_label

        assert status_label("subscription_status", "وضع-مجهول") == "وضع-مجهول"

    def test_unknown_kind_returns_raw_value(self):
        from app.core.labels import status_label

        assert status_label("نوع-غير-معروف", "x") == "x"


# ═══════════════════════════════════════════════════════════════════════
# فجوات الجولة الثانية — assert_user_belongs بدون مدارس + OSError في listdir
# ═══════════════════════════════════════════════════════════════════════


class TestApiTenancyAbortPaths:
    def test_assert_user_belongs_403_when_no_accessible_schools(self, client, app):
        """مستخدم بلا صلة بأي مدرسة يطلب مستخدماً آخر → 403 (api_tenancy:93)."""
        from app.core.api_tenancy import assert_user_belongs_to_accessible_school
        from app.models.user import User
        from flask_login import login_user
        from werkzeug.exceptions import Forbidden

        uid = make_user(app, role="student")  # بلا school_id
        other = make_user(app, role="student")
        with app.test_request_context():
            with app.app_context():
                login_user(User.query.get(uid))
                target = User.query.get(other)
                try:
                    assert_user_belongs_to_accessible_school(target)
                except Forbidden:
                    pass
                else:
                    raise AssertionError("كان يجب رفع 403")


class TestPdfFontOSError:
    def test_find_font_file_survives_listdir_oserror(self, tmp_path):
        from unittest.mock import patch

        from app.core import pdf

        locked_dir = tmp_path / "locked"
        locked_dir.mkdir()
        with (
            patch.object(pdf, "_DIRS_EXTRA", [str(locked_dir), str(tmp_path)]),
            patch.object(pdf.os, "name", "posix"),
            patch.object(pdf.os, "listdir", side_effect=OSError("permission denied")),
        ):
            # كل المجلدات تفشل listdir → None بلا انهيار (103-104)
            assert pdf._find_font_file() is None

    def test_find_font_file_scans_remaining_dirs_after_oserror(self, tmp_path):
        from unittest.mock import patch

        from app.core import pdf

        first_dir = tmp_path / "first"
        first_dir.mkdir()
        font_file = tmp_path / pdf._ARABIC_FONT_CANDIDATES[0]
        font_file.write_bytes(b"fake ttf")

        real_listdir = __import__("os").listdir

        def flaky_listdir(path):
            # المجلد الأول (الموجود فعلاً) يفشل listdir — الثاني سليم
            if str(path) == str(first_dir):
                raise OSError("transient failure")
            return real_listdir(path)

        with (
            patch.object(pdf, "_DIRS_EXTRA", [str(first_dir), str(tmp_path)]),
            patch.object(pdf.os, "name", "posix"),
            patch.object(pdf.os, "listdir", side_effect=flaky_listdir),
        ):
            found = pdf._find_font_file()
        assert found is not None and found.endswith(".ttf")
