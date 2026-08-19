"""اختبارات وضع عدم الاتصال للعميل"""

import pytest
import uuid


def _unique_domain():
    return f"test-{uuid.uuid4().hex[:8]}.org"


def _unique_email():
    return f"student-{uuid.uuid4().hex[:8]}@test.com"


def test_lesson_model_has_offline_available(app):
    """نموذج الدرس يحتوي على حقل is_offline_available"""
    with app.app_context():
        from app.extensions import db
        from app.models.school import School, Grade, Subject
        from app.models.class_room import ClassRoom
        from app.models.content import Lesson

        school = School(name_ar="مدرسة", name_en="School", domain=_unique_domain())
        db.session.add(school)
        db.session.commit()

        grade = Grade(school_id=school.id, grade_level=10, name_ar="العاشر")
        subject = Subject(name_ar="رياضيات")
        db.session.add_all([grade, subject])
        db.session.commit()

        class_room = ClassRoom(school_id=school.id, grade_id=grade.id, subject_id=subject.id,
                               join_code="TEST30", name="صف")
        db.session.add(class_room)
        db.session.commit()

        lesson = Lesson(class_id=class_room.id, title="درس اختبار", status="published",
                        is_offline_available=True)
        db.session.add(lesson)
        db.session.commit()

        # Reload and check
        loaded = Lesson.query.get(lesson.id)
        assert loaded.is_offline_available is True


def test_offline_service_mark_for_download(app):
    """خدمة وضع عدم الاتصال موجودة وتعمل"""
    with app.app_context():
        from app.extensions import db
        from app.models.school import School, Grade, Subject
        from app.models.class_room import ClassRoom
        from app.models.content import Lesson, LessonAttachment
        from app.models.user import User, UserRole
        from app.services.offline import mark_for_download

        school = School(name_ar="مدرسة", name_en="School", domain=_unique_domain())
        db.session.add(school)
        db.session.commit()

        grade = Grade(school_id=school.id, grade_level=10, name_ar="العاشر")
        subject = Subject(name_ar="رياضيات")
        db.session.add_all([grade, subject])
        db.session.commit()

        class_room = ClassRoom(school_id=school.id, grade_id=grade.id, subject_id=subject.id,
                               join_code="TEST31", name="صف")
        db.session.add(class_room)
        db.session.commit()

        lesson = Lesson(class_id=class_room.id, title="درس", status="published")
        db.session.add(lesson)
        db.session.commit()

        attachment = LessonAttachment(lesson_id=lesson.id, kind="video",
                                      stored_name="test.mp4", original_name="test.mp4")
        db.session.add(attachment)
        db.session.commit()

        student = User(email=_unique_email(), name_ar="طالب", role=UserRole.student,
                       password_hash="hash", approval_status="approved", is_active=True)
        db.session.add(student)
        db.session.commit()

        result = mark_for_download(student.id, attachment.id, lesson.id)
        assert result is not None
        assert result.student_id == student.id
        assert result.attachment_id == attachment.id


def test_sw_js_has_lesson_cache_strategy():
    """ملف sw.js يحتوي على استراتيجية تخزين الدروس"""
    with open("app/static/sw.js", "r") as f:
        content = f.read()
    assert "LESSON_CACHE" in content
    assert "azad-lessons-v1" in content
    assert "/content/lessons/" in content


def test_offline_sync_js_exists():
    """ملف app.js يحتوي على دالة initOfflineSync"""
    with open("app/static/js/app.js", "r", encoding="utf-8") as f:
        content = f.read()
    assert "initOfflineSync" in content
    assert "azad-offline-progress" in content
    assert "localStorage.getItem" in content