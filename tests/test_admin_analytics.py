"""اختبارات لوحة تحليلات المشرف"""

import pytest
from datetime import UTC, datetime, timedelta

from app.services.analytics import get_analytics_data


def test_get_analytics_data_returns_all_keys(app):
    """تتأكد من وجود جميع المفاتيح في البيانات المرجعة"""
    with app.app_context():
        data = get_analytics_data(days=30)
        assert "dau" in data
        assert "new_users" in data
        assert "role_distribution" in data
        assert "total_lessons" in data
        assert "tutoring_sessions" in data
        assert "family_links" in data


def test_analytics_dau_calculation(app):
    """DAU يحسب بشكل صحيح"""
    from app.extensions import db
    from app.models.user import User, UserRole
    from app.models.school import School, Grade, Subject
    from app.models.class_room import ClassRoom, ClassMember
    from app.models.content import Lesson
    from app.models.progress import StudentProgress

    with app.app_context():
        # Create test data
        school = School(name_ar="مدرسة", name_en="School", domain="test.org")
        db.session.add(school)
        db.session.commit()

        grade = Grade(school_id=school.id, grade_level=10, name_ar="العاشر")
        subject = Subject(name_ar="رياضيات")
        db.session.add_all([grade, subject])
        db.session.commit()

        class_room = ClassRoom(school_id=school.id, grade_id=grade.id, subject_id=subject.id,
                               join_code="TEST10", name="صف العاشر")
        db.session.add(class_room)
        db.session.commit()

        lesson = Lesson(class_id=class_room.id, title="درس", status="published")
        db.session.add(lesson)
        db.session.commit()

        student = User(email="student@test.com", name_ar="طالب", role=UserRole.student,
                       password_hash="hash", approval_status="approved", is_active=True)
        db.session.add(student)
        db.session.commit()

        member = ClassMember(class_id=class_room.id, user_id=student.id, status="active")
        db.session.add(member)
        db.session.commit()

        # Add progress (activity)
        progress = StudentProgress(student_id=student.id, lesson_id=lesson.id,
                                   class_id=class_room.id, status="completed", progress_pct=100)
        db.session.add(progress)
        db.session.commit()

        data = get_analytics_data(days=30)
        assert len(data["dau"]) >= 1
        assert data["dau"][0]["count"] >= 1


def test_analytics_new_users_count(app):
    """عدد التسجيلات الجديدة"""
    from app.extensions import db
    from app.models.user import User, UserRole

    with app.app_context():
        # Create new user
        user = User(email="newuser@test.com", name_ar="مستخدم جديد", role=UserRole.student,
                    password_hash="hash", approval_status="approved", is_active=True)
        db.session.add(user)
        db.session.commit()

        data = get_analytics_data(days=30)
        # Should have at least 1 new user
        assert sum(d["count"] for d in data["new_users"]) >= 1


def test_analytics_route_renders(client, admin_user):
    """مسار التحليلات يعرض بنجاح"""
    # Login as admin
    client.post("/auth/login", data={
        "email": admin_user.email,
        "password": "TestPass123!"
    }, follow_redirects=True)

    response = client.get("/admin/analytics")
    assert response.status_code == 200
    assert b"Analytics" in response.data or b"\xd9\x84\xd9\x88\xd8\xad\xd8\xa9" in response.data
    assert b"DAU" in response.data or b"Active" in response.data