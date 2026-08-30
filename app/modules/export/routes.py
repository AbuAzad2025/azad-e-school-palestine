"""مسارات التصدير"""

from app.core.permissions import class_teach_required
from flask import Response

from . import bp


@bp.get("/<int:class_id>/students")
@class_teach_required
def students_excel(class_id, class_room=None):
    from app.services.export import export_students_excel

    data = export_students_excel(class_id)
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=students_{class_id}.xlsx"},
    )


@bp.get("/<int:class_id>/grades")
@class_teach_required
def grades_excel(class_id, class_room=None):
    from app.services.export import export_grades_excel

    data = export_grades_excel(class_id)
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=grades_{class_id}.xlsx"},
    )


@bp.get("/<int:class_id>/progress")
@class_teach_required
def progress_excel(class_id, class_room=None):
    from app.services.export import export_progress_excel

    data = export_progress_excel(class_id)
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=progress_{class_id}.xlsx"},
    )
