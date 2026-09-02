"""مسارات تتبع تقدم الطالب"""

from app.core.permissions import class_teach_required, role_required
from app.models.class_room import ClassRoom
from app.models.user import UserRole
from app.services.access import can_view_class
from app.services.progress import (
    class_progress_overview,
    record_lesson_view,
    student_class_progress,
    update_time_spent,
    update_video_progress,
)
from flask import abort, jsonify, render_template, request
from flask_login import current_user, login_required

from . import bp


def _class_or_404(class_id):
    class_room = ClassRoom.query.filter_by(id=class_id, deleted_at=None).first()
    if not class_room:
        abort(404)
    return class_room


@bp.get("/class/<int:class_id>")
@class_teach_required
def class_overview(class_id, class_room=None):
    """نظرة عامة على تقدم جميع الطلاب في الصف."""
    overview = class_progress_overview(class_id)
    return render_template("progress/class_overview.html", class_room=class_room, overview=overview)


@bp.get("/class/<int:class_id>/student/<int:student_id>")
@login_required
def student_detail(class_id, student_id):
    """تقدم طالب محدد في صف معين."""
    class_room = _class_or_404(class_id)
    if not can_view_class(class_room, current_user):
        abort(403)
    if current_user.role == UserRole.student and current_user.id != student_id:
        abort(403)
    if current_user.role == UserRole.parent:
        from app.services.family import is_parent_of

        if not is_parent_of(current_user.id, student_id):
            abort(403)
    progress = student_class_progress(student_id, class_id)
    return render_template(
        "progress/student_detail.html",
        class_room=class_room,
        student_id=student_id,
        progress=progress,
    )


@bp.post("/lesson/<int:lesson_id>/heartbeat")
@login_required
@role_required(UserRole.student)
def lesson_heartbeat(lesson_id):
    """AJAX: تحديث وقت المشاهدة للدرس."""
    from app.models.class_room import ClassMember
    from app.models.content import Lesson

    lesson = Lesson.query.get_or_404(lesson_id)
    # Ensure student is a member of the lesson's class
    _is_member = ClassMember.query.filter_by(class_id=lesson.class_id, user_id=current_user.id, status="active").first()
    if not _is_member:
        abort(403)
    seconds = request.get_json(silent=True) or {}
    additional = seconds.get("seconds", 30)
    progress = update_time_spent(current_user.id, lesson_id, additional)
    if not progress:
        progress = record_lesson_view(current_user.id, lesson_id, lesson.class_id)
    return jsonify(
        status=progress.status,
        progress_pct=progress.progress_pct,
        seconds_spent=progress.seconds_spent,
    )


@bp.post("/video/<int:attachment_id>/update")
@login_required
@role_required(UserRole.student)
def video_update(attachment_id):
    """AJAX: تحديث تقدم الفيديو."""
    from app.models.class_room import ClassMember
    from app.models.content import LessonAttachment

    attachment = LessonAttachment.query.get_or_404(attachment_id)
    # Ensure student is a member of the lesson's class
    _cls_id = attachment.lesson.class_id
    _is_member = ClassMember.query.filter_by(class_id=_cls_id, user_id=current_user.id, status="active").first()
    if not _is_member:
        abort(403)
    data = request.get_json(silent=True) or {}
    seconds_watched = data.get("seconds_watched", 0)
    total_seconds = data.get("total_seconds", 0)
    progress = update_video_progress(
        current_user.id,
        attachment_id,
        attachment.lesson_id,
        attachment.lesson.class_id,
        seconds_watched,
        total_seconds,
    )
    return jsonify(
        completed=progress.completed,
        seconds_watched=progress.seconds_watched,
    )


@bp.get("/my")
@login_required
@role_required(UserRole.student)
def my_progress():
    """تقدمي في جميع صفوفي (batch — لا N+1)."""
    from app.models.class_room import ClassMember
    from app.models.content import Lesson
    from app.models.progress import StudentProgress
    from sqlalchemy.orm import selectinload

    memberships = (
        ClassMember.query.filter_by(user_id=current_user.id, status="active")
        .options(selectinload(ClassMember.class_room))
        .all()
    )
    class_ids = [m.class_id for m in memberships]
    if not class_ids:
        return render_template("progress/my_progress.html", classes_progress=[])

    # Batch: جلب كل الدروس المنشورة لجميع الصفوف في استعلام واحد
    all_lessons = (
        Lesson.query.filter(Lesson.class_id.in_(class_ids), Lesson.status == "published")
        .order_by(Lesson.class_id, Lesson.sort_order)
        .all()
    )
    lessons_by_class: dict[int, list] = {}
    for lesson in all_lessons:
        lessons_by_class.setdefault(lesson.class_id, []).append(lesson)

    # Batch: جلب كل سجلات التقدم للطالب في جميع صفوفه
    all_progress = StudentProgress.query.filter(
        StudentProgress.student_id == current_user.id,
        StudentProgress.class_id.in_(class_ids),
    ).all()
    progress_map: dict[tuple[int, int], StudentProgress] = {(p.lesson_id, p.class_id): p for p in all_progress}

    classes_progress = []
    for m in memberships:
        lessons = lessons_by_class.get(m.class_id, [])
        lessons_data = []
        for lesson in lessons:
            prog = progress_map.get((lesson.id, m.class_id))
            lessons_data.append(
                {
                    "lesson": lesson,
                    "status": prog.status if prog else "not_started",
                    "seconds_spent": prog.seconds_spent if prog else 0,
                    "progress_pct": prog.progress_pct if prog else 0,
                }
            )
        classes_progress.append(
            {
                "class_room": m.class_room,
                "lessons": lessons_data,
            }
        )
    return render_template("progress/my_progress.html", classes_progress=classes_progress)
