"""مسارات التصدير"""

from app.core.permissions import role_required
from app.models.class_room import ClassRoom
from app.models.user import UserRole
from app.services.access import can_teach_class
from flask import Response, abort
from flask_login import current_user, login_required

from . import bp


def _class_or_404(class_id):
    class_room = ClassRoom.query.filter_by(id=class_id, deleted_at=None).first()
    if not class_room:
        abort(404)
    return class_room


@bp.get("/<int:class_id>/students")
@login_required
@role_required(UserRole.teacher, UserRole.school_admin, UserRole.super_admin)
def students_excel(class_id):
    class_room = _class_or_404(class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    from app.services.export import export_students_excel

    data = export_students_excel(class_id)
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=students_{class_id}.xlsx"},
    )


@bp.get("/<int:class_id>/grades")
@login_required
@role_required(UserRole.teacher, UserRole.school_admin, UserRole.super_admin)
def grades_excel(class_id):
    class_room = _class_or_404(class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    from app.services.export import export_grades_excel

    data = export_grades_excel(class_id)
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=grades_{class_id}.xlsx"},
    )


@bp.get("/<int:class_id>/progress")
@login_required
@role_required(UserRole.teacher, UserRole.school_admin, UserRole.super_admin)
def progress_excel(class_id):
    class_room = _class_or_404(class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    from app.services.export import export_progress_excel

    data = export_progress_excel(class_id)
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=progress_{class_id}.xlsx"},
    )
