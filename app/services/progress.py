"""خدمات تتبع تقدم الطالب — الحضور والإنتاج في المنصة."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from app.core.db import tx
from app.extensions import db
from app.models.content import Lesson
from app.models.progress import StudentProgress, VideoProgress


def record_lesson_view(student_id: int, lesson_id: int, class_id: int) -> StudentProgress:
    """تسجيل مشاهدة الطالب للدرس (upsert)."""
    existing = StudentProgress.query.filter_by(student_id=student_id, lesson_id=lesson_id).first()
    if existing:
        if existing.status == "not_started":
            existing.status = "in_progress"
            existing.started_at = datetime.now(UTC)
        return existing

    def _create():
        return StudentProgress(
            student_id=student_id,
            lesson_id=lesson_id,
            class_id=class_id,
            status="in_progress",
            started_at=datetime.now(UTC),
        )

    return tx(_create)


def update_time_spent(student_id: int, lesson_id: int, additional_seconds: int) -> StudentProgress | None:
    """تحديث الوقت المسجّل للطالب في الدرس."""
    progress = StudentProgress.query.filter_by(student_id=student_id, lesson_id=lesson_id).first()
    if not progress:
        return None

    def _update():
        progress.seconds_spent += additional_seconds
        lesson = db.session.get(Lesson, lesson_id)
        if lesson:
            total_attachments = len(lesson.attachments) or 1
            progress.progress_pct = min(100, (progress.seconds_spent // 60) * 100 // max(total_attachments * 5, 1))
        if progress.progress_pct >= 100 and progress.status != "completed":
            progress.status = "completed"
            progress.completed_at = datetime.now(UTC)

    tx(_update)
    return progress


def update_video_progress(
    student_id: int,
    attachment_id: int,
    lesson_id: int,
    class_id: int,
    seconds_watched: int,
    total_seconds: int,
) -> VideoProgress:
    """تحديث تقدم الفيديو (upsert)."""
    existing = VideoProgress.query.filter_by(student_id=student_id, attachment_id=attachment_id).first()
    if existing:

        def _update():
            existing.seconds_watched = max(existing.seconds_watched, seconds_watched)
            existing.total_seconds = total_seconds
            existing.last_watched_at = datetime.now(UTC)
            if total_seconds > 0 and existing.seconds_watched >= total_seconds * 0.9:
                existing.completed = True

        tx(_update)
        return existing

    def _create():
        completed = total_seconds > 0 and seconds_watched >= total_seconds * 0.9
        return VideoProgress(
            student_id=student_id,
            attachment_id=attachment_id,
            lesson_id=lesson_id,
            class_id=class_id,
            seconds_watched=seconds_watched,
            total_seconds=total_seconds,
            completed=completed,
            last_watched_at=datetime.now(UTC),
        )

    return tx(_create)


def student_class_progress(student_id: int, class_id: int) -> list[dict]:
    """تقدم الطالب في صف معين — كل الدروس ونسبة الإنجاز."""
    lessons = Lesson.query.filter_by(class_id=class_id, status="published").order_by(Lesson.sort_order).all()
    progress_map = {
        p.lesson_id: p for p in StudentProgress.query.filter_by(student_id=student_id, class_id=class_id).all()
    }
    result = []
    for lesson in lessons:
        prog = progress_map.get(lesson.id)
        result.append(
            {
                "lesson": lesson,
                "status": prog.status if prog else "not_started",
                "seconds_spent": prog.seconds_spent if prog else 0,
                "progress_pct": prog.progress_pct if prog else 0,
            }
        )
    return result


def class_progress_overview(class_id: int) -> list[dict]:
    """نظرة عامة على تقدم جميع الطلاب في صف معين."""
    from app.models.class_room import ClassMember
    from app.models.user import User

    members = (
        ClassMember.query.filter_by(class_id=class_id, status="active").join(User, ClassMember.user_id == User.id).all()
    )
    total_lessons = Lesson.query.filter_by(class_id=class_id, status="published").count()
    if total_lessons == 0:
        return []

    result = []
    for member in members:
        completed = StudentProgress.query.filter_by(
            student_id=member.user_id, class_id=class_id, status="completed"
        ).count()
        avg_progress = (
            db.session.query(func.avg(StudentProgress.progress_pct))
            .filter(StudentProgress.student_id == member.user_id, StudentProgress.class_id == class_id)
            .scalar()
            or 0
        )
        result.append(
            {
                "student": member.user,
                "completed_lessons": completed,
                "total_lessons": total_lessons,
                "avg_progress": round(float(avg_progress), 1),
            }
        )
    return result


def last_active_days(student_id: int) -> list[str]:
    """أيام نشاط الطالب (آخر 30 يوم) — كـ "حضور" إلكتروني."""
    since = datetime.now(UTC) - timedelta(days=30)
    rows = (
        StudentProgress.query.filter(
            StudentProgress.student_id == student_id,
            StudentProgress.updated_at >= since,
        )
        .with_entities(func.date(StudentProgress.updated_at))
        .distinct()
        .all()
    )
    return [str(r[0]) for r in rows if r[0]]
