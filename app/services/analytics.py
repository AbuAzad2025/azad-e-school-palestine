"""خدمات التحليلات للوحة المشرف."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from app.extensions import db
from app.models.content import Lesson
from app.models.family import FamilyLink
from app.models.progress import StudentProgress
from app.models.tutoring import TutoringSession
from app.models.user import User


def get_analytics_data(days: int = 30) -> dict:
    now = datetime.now(UTC)
    since = now - timedelta(days=days)

    # 1. Daily Active Users (DAU) — students with progress in last 7 days
    dau = (
        db.session.query(func.date(StudentProgress.created_at), func.count(func.distinct(StudentProgress.student_id)))
        .filter(StudentProgress.created_at >= now - timedelta(days=7))
        .group_by(func.date(StudentProgress.created_at))
        .all()
    )

    # 2. New registrations
    new_users = (
        db.session.query(func.date(User.created_at), func.count())
        .filter(User.created_at >= since)
        .group_by(func.date(User.created_at))
        .all()
    )

    # 3. Role distribution
    role_dist = db.session.query(User.role, func.count()).filter(User.is_active).group_by(User.role).all()

    # 4. Lesson count
    total_lessons = Lesson.query.filter_by(status="published").count()

    # 5. Tutoring sessions
    tutoring_count = TutoringSession.query.filter(
        TutoringSession.created_at >= since, TutoringSession.status.in_(["completed", "ended"])
    ).count()

    # 6. Family links (parent adoption)
    family_links = FamilyLink.query.count()

    return {
        "dau": [{"date": str(d), "count": c} for d, c in dau],
        "new_users": [{"date": str(d), "count": c} for d, c in new_users],
        "role_distribution": {str(r): c for r, c in role_dist},
        "total_lessons": total_lessons,
        "tutoring_sessions": tutoring_count,
        "family_links": family_links,
    }
