"""خدمات الشارات والتحفيز (Gamification) — منطق منح الشارات."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from app.core.db import tx
from app.extensions import db
from app.models.gamification import Badge, BadgeCriteriaType, StudentBadge
from app.models.progress import StudentProgress


def get_active_badges():
    """جلب كل الشارات النشطة."""
    return Badge.query.filter_by(is_active=True).all()


def get_student_badges(student_id: int):
    """جلب شارات الطالب مع معلومات الشارة."""
    return (
        StudentBadge.query.filter_by(student_id=student_id)
        .join(Badge)
        .options(db.joinedload(StudentBadge.badge))
        .order_by(StudentBadge.earned_at.desc())
        .all()
    )


def has_badge(student_id: int, badge_id: int) -> bool:
    """التحقق مما إذا كان الطالب يملك شارة معينة."""
    return StudentBadge.query.filter_by(student_id=student_id, badge_id=badge_id).first() is not None


def award_badge(student_id: int, badge_id: int) -> StudentBadge | None:
    """منح شارة لطالب (لا يمنح إذا كانت موجودة مسبقاً)."""
    if has_badge(student_id, badge_id):
        return None

    def _award():
        sb = StudentBadge(student_id=student_id, badge_id=badge_id)
        db.session.add(sb)
        return sb

    return tx(_award)


def check_and_award_badges(student_id: int, event_type: str, event_data: dict | None = None) -> list[StudentBadge]:
    """التحقق من شروط منح الشارات ومنحها عند استيفاء المعايير.

    يُستدعى بعد: تقديم اختبار، إكمال درس، تسجيل دخول يومي.

    Args:
        student_id: معرف الطالب
        event_type: نوع الحدث ('quiz_submitted', 'lesson_completed', 'daily_login', 'assignment_submitted')
        event_data: بيانات إضافية للحدث

    Returns:
        قائمة بالشارات التي تم منحها حديثاً
    """
    new_badges = []

    # جلب الشارات النشطة التي لا يملكها الطالب
    earned_badge_ids = {sb.badge_id for sb in get_student_badges(student_id)}
    candidate_badges = Badge.query.filter(Badge.is_active.is_(True), Badge.id.notin_(earned_badge_ids)).all()

    for badge in candidate_badges:
        should_award = False

        if badge.criteria_type == BadgeCriteriaType.first_quiz:
            if event_type == "quiz_submitted":
                should_award = True

        elif badge.criteria_type == BadgeCriteriaType.perfect_score:
            if event_type == "quiz_submitted" and event_data:
                score = event_data.get("score")
                max_score = event_data.get("max_score")
                if score is not None and max_score is not None and score >= max_score:
                    should_award = True

        elif badge.criteria_type == BadgeCriteriaType.streak_7_days:
            # التحقق من سلسلة 7 أيام متتالية
            if _check_streak(student_id, 7):
                should_award = True

        elif badge.criteria_type == BadgeCriteriaType.course_complete:
            if event_type == "lesson_completed" and event_data:
                if _check_course_complete(student_id, event_data.get("class_id")):
                    should_award = True

        elif badge.criteria_type == BadgeCriteriaType.early_bird:
            if event_type == "assignment_submitted" and event_data:
                deadline = event_data.get("deadline")
                submitted_at = event_data.get("submitted_at")
                if deadline and submitted_at:
                    deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                    submitted_dt = datetime.fromisoformat(submitted_at.replace("Z", "+00:00"))
                    if (deadline_dt - submitted_dt).total_seconds() >= 24 * 3600:
                        should_award = True

        if should_award:
            awarded = award_badge(student_id, badge.id)
            if awarded:
                new_badges.append(awarded)

    return new_badges


def _check_streak(student_id: int, days: int) -> bool:
    """التحقق من وجود سلسلة نشاط متتالية لعدد أيام محدد."""
    from app.models.progress import StudentProgress

    # جلب أيام النشاط الفريدة (أيام لها تقدم)
    progress_days = (
        db.session.query(func.date(StudentProgress.completed_at))
        .filter(
            StudentProgress.student_id == student_id,
            StudentProgress.status == "completed",
            StudentProgress.completed_at.isnot(None),
        )
        .distinct()
        .order_by(func.date(StudentProgress.completed_at).desc())
        .all()
    )

    if len(progress_days) < days:
        return False

    # التحقق من التسلسل
    today = datetime.now(UTC).date()
    streak = 0
    for i, (day,) in enumerate(progress_days):
        expected = today - timedelta(days=i)
        if day == expected:
            streak += 1
        else:
            break

    return streak >= days


def _check_course_complete(student_id: int, class_id: int | None) -> bool:
    """التحقق مما إذا أكمل الطالب جميع دروس الصف."""
    if not class_id:
        return False

    from app.models.content import Lesson

    total_lessons = Lesson.query.filter_by(class_id=class_id, status="published").count()
    if total_lessons == 0:
        return False

    completed_lessons = StudentProgress.query.filter(
        StudentProgress.student_id == student_id,
        StudentProgress.class_id == class_id,
        StudentProgress.status == "completed",
    ).count()

    return completed_lessons >= total_lessons
