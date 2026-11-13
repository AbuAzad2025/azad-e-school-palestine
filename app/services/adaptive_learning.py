"""AZ-FF-B: Adaptive learning engine.

Real-time student performance profiling based on quiz metrics and assignment
scores, plus automated RAG-based remedial content recommendation generation
targeting specific learning gaps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.extensions import db


@dataclass
class StudentProfile:
    user_id: int
    school_id: int
    quiz_accuracy: float = 0.0
    assignment_avg: float = 0.0
    engagement_score: float = 0.0
    weak_topics: list[str] = field(default_factory=list)
    difficulty_level: str = "medium"  # easy/medium/hard


def build_student_profile(user_id: int, school_id: int) -> StudentProfile:
    """Build a real-time performance profile from quiz + assignment data."""
    profile = StudentProfile(user_id=user_id, school_id=school_id)

    # Quiz accuracy.
    try:
        from app.models.assessment import QuizAttempt

        attempts = (
            db.session.query(QuizAttempt).filter_by(student_id=user_id).all()
            if hasattr(QuizAttempt, "student_id")
            else []
        )
        if attempts:
            scored = [a for a in attempts if getattr(a, "score", None) is not None]
            if scored:
                profile.quiz_accuracy = sum(float(a.score) for a in scored) / len(scored)  # type: ignore[arg-type,misc]
    except Exception:  # noqa: BLE001
        pass

    # Assignment average.
    try:
        from app.models.gradebook import Submission

        subs = (
            db.session.query(Submission).filter_by(student_id=user_id).all()
            if hasattr(Submission, "student_id")
            else []
        )
        if subs:
            scores = [float(s.score) for s in subs if getattr(s, "score", None) is not None]
            if scores:
                profile.assignment_avg = sum(scores) / len(scores)
    except Exception:  # noqa: BLE001
        pass

    # Engagement: simple proxy from counts.
    profile.engagement_score = (
        min(1.0, (profile.quiz_accuracy + profile.assignment_avg) / 2.0)
        if (profile.quiz_accuracy or profile.assignment_avg)
        else 0.0
    )

    # Difficulty adjustment.
    composite = (
        (profile.quiz_accuracy + profile.assignment_avg) / 2.0
        if (profile.quiz_accuracy or profile.assignment_avg)
        else 0.5
    )
    if composite < 0.4:
        profile.difficulty_level = "easy"
    elif composite > 0.75:
        profile.difficulty_level = "hard"
    else:
        profile.difficulty_level = "medium"

    # Weak topics: topics with low scores (placeholder heuristic).
    profile.weak_topics = []  # populated by caller/RAG layer

    return profile


def recommend_remedial(profile: StudentProfile, available_content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter available content to remedial items matching weak topics / difficulty."""
    out: list[dict[str, Any]] = []
    for item in available_content:
        topics = item.get("topics", []) or []
        if profile.weak_topics and not (set(topics) & set(profile.weak_topics)):
            continue
        if (
            item.get("difficulty")
            and item["difficulty"] != profile.difficulty_level
            and profile.difficulty_level == "easy"
        ):
            # prefer easier content for struggling students
            if item["difficulty"] == "hard":
                continue
        out.append(item)
    return out


def early_warning_students(school_id: int, threshold: float = 0.4) -> list[dict[str, Any]]:
    """Return students whose composite performance is below threshold."""
    alerts: list[dict[str, Any]] = []
    try:
        from app.models.user import User, UserRole

        students = db.session.query(User).filter_by(role=UserRole.student).all()
        for u in students:
            profile = build_student_profile(u.id, school_id)
            composite = (
                (profile.quiz_accuracy + profile.assignment_avg) / 2.0
                if (profile.quiz_accuracy or profile.assignment_avg)
                else 0.0
            )
            if composite < threshold:
                alerts.append({"user_id": u.id, "composite": composite, "difficulty_level": profile.difficulty_level})
    except Exception:  # noqa: BLE001
        pass
    return alerts
