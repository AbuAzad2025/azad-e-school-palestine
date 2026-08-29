"""اختبارات C6 — تتبع تقدم الطالب (record_lesson_view, update_time_spent, update_video_progress)."""

from tests.conftest import (
    make_attachment,
    make_class,
    make_grade,
    make_lesson,
    make_school,
    make_student_progress,
    make_subject,
    make_user,
)


def test_record_lesson_view_creates_progress(app):
    """إنشاء تقدم جديد عند مشاهدة الدرس لأول مرة."""
    from app.services.progress import record_lesson_view

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        lesson_id = make_lesson(app, class_id)
        result = record_lesson_view(student_id, lesson_id, class_id)
        assert result.status == "in_progress"
        assert result.student_id == student_id
        assert result.lesson_id == lesson_id


def test_record_lesson_view_upsert(app):
    """تحديث موجود بدلاً من إنشاء جديد."""
    from app.services.progress import record_lesson_view

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        lesson_id = make_lesson(app, class_id)
        r1 = record_lesson_view(student_id, lesson_id, class_id)
        r2 = record_lesson_view(student_id, lesson_id, class_id)
        assert r1.id == r2.id


def test_update_time_spent(app):
    """تحديث الوقت المسجّل للطالب."""
    from app.services.progress import update_time_spent

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        lesson_id = make_lesson(app, class_id)
        make_student_progress(app, student_id, lesson_id, class_id, seconds=100)
        result = update_time_spent(student_id, lesson_id, 50)
        assert result.seconds_spent == 150


def test_update_video_progress_completion(app):
    """اكتمال الفيديو عند 90% من المشاهدة."""
    from app.services.progress import update_video_progress

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        lesson_id = make_lesson(app, class_id)
        att_id = make_attachment(app, lesson_id)
        result = update_video_progress(student_id, att_id, lesson_id, class_id, 95, 100)
        assert result.completed is True
        assert result.seconds_watched == 95


def test_video_progress_not_completed_below_90(app):
    """الفيديو غير مكتمل إذا المشاهدة أقل من 90%."""
    from app.services.progress import update_video_progress

    school_id = make_school(app)
    student_id = make_user(app, role="student", school_id=school_id)
    grade_id = make_grade(app, school_id)
    subject_id = make_subject(app)
    class_id = make_class(app, school_id, grade_id, subject_id)
    with app.app_context():
        lesson_id = make_lesson(app, class_id)
        att_id = make_attachment(app, lesson_id)
        result = update_video_progress(student_id, att_id, lesson_id, class_id, 50, 100)
        assert result.completed is False
