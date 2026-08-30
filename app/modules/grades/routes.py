"""مسارات الواجبات والدرجات والحضور"""

from datetime import date

from app.core.permissions import class_access_required, class_teach_required
from app.models.class_room import ClassMember, ClassRoom
from app.models.gradebook import GradeItem, Submission
from app.models.user import UserRole
from app.services.access import can_teach_class, can_view_class
from app.services.communication import audit, notify
from app.services.gradebook import (
    attendance_days,
    create_assignment,
    create_category,
    create_grade_item,
    get_attendance,
    grade_submission,
    list_assignments,
    list_categories,
    list_submissions,
    record_attendance,
    set_grade,
    student_gradebook,
    submit_assignment,
)
from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from . import bp
from .forms import AssignmentForm, CategoryForm, GradeItemForm, GradeSubmissionForm, SubmissionForm


def _class_or_404(class_id):
    class_room = ClassRoom.query.filter_by(id=class_id, deleted_at=None).first()
    if not class_room:
        abort(404)
    return class_room


def _students(class_id):
    return (
        ClassMember.query.filter_by(class_id=class_id, status="active")
        .options(joinedload(ClassMember.user))
        .order_by(ClassMember.joined_at)
        .all()
    )


@bp.get("/<int:class_id>/assignments")
@class_access_required
def assignments(class_id, class_room=None):
    form = AssignmentForm()
    subs = {}
    if current_user.role == UserRole.student:
        subs = {s.assignment_id: s for s in Submission.query.filter_by(student_id=current_user.id).all()}
    return render_template(
        "grades/assignments.html",
        class_room=class_room,
        assignments=list_assignments(class_id),
        subs=subs,
        can_teach=can_teach_class(class_room, current_user),
        form=form,
    )


@bp.post("/<int:class_id>/assignments")
@class_teach_required
def assignment_create(class_id, class_room=None):
    form = AssignmentForm()
    if form.validate_on_submit():
        assignment, error = create_assignment(
            class_id=class_id,
            title=form.title.data,
            body=form.body.data,
            max_mark=form.max_mark.data,
            created_by=current_user.id,
        )
        if error:
            flash(_(error), "danger")
        elif assignment is not None:
            audit("assignment.create", "assignments", assignment.id)
            flash(_("نُشر الواجب."), "success")
    return redirect(url_for("grades.assignments", class_id=class_id))


@bp.get("/<int:class_id>/assignments/<int:assignment_id>")
@class_access_required
def assignment_detail(class_id, assignment_id, class_room=None):
    assignment = next((a for a in list_assignments(class_id) if a.id == assignment_id), None)
    if not assignment:
        abort(404)
    can_teach = can_teach_class(class_room, current_user)
    submissions = list_submissions(assignment) if can_teach else []
    my_sub = None
    if current_user.role == UserRole.student:
        my_sub = next((s for s in list_submissions(assignment) if s.student_id == current_user.id), None)
    return render_template(
        "grades/assignment_detail.html",
        class_room=class_room,
        assignment=assignment,
        submissions=submissions,
        my_sub=my_sub,
        can_teach=can_teach,
        sub_form=SubmissionForm(),
        grade_form=GradeSubmissionForm(),
    )


@bp.post("/<int:class_id>/assignments/<int:assignment_id>/submit")
@class_access_required
def assignment_submit(class_id, assignment_id, class_room=None):
    assignment = next((a for a in list_assignments(class_id) if a.id == assignment_id), None)
    if not assignment:
        abort(404)
    form = SubmissionForm()
    if form.validate_on_submit():
        sub, error = submit_assignment(assignment, current_user.id, body=form.body.data, file=form.file.data)
        if error:
            flash(_(error), "danger")
        elif sub is not None:
            audit("assignment.submit", "submissions", sub.id)
            notify(assignment.created_by, "assignment", _("تسليم واجب جديد"), current_user.name_ar)
            flash(_("سُلّم واجبك."), "success")
    return redirect(url_for("grades.assignment_detail", class_id=class_id, assignment_id=assignment_id))


@bp.get("/submissions/<int:submission_id>/file")
@login_required
def submission_file(submission_id):
    from flask import current_app, send_from_directory

    submission = Submission.query.get_or_404(submission_id)
    class_room = _class_or_404(submission.assignment.class_id)
    if not can_view_class(class_room, current_user):
        abort(403)
    if not submission.file:
        abort(404)
    folder = (current_app.config["UPLOAD_FOLDER"] / submission.file).parent
    return send_from_directory(folder, submission.file.rsplit("/", 1)[-1], as_attachment=True)


@bp.post("/submissions/<int:submission_id>/grade")
@login_required
def submission_grade(submission_id):
    submission = Submission.query.get_or_404(submission_id)
    class_room = _class_or_404(submission.assignment.class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    form = GradeSubmissionForm()
    if form.validate_on_submit():
        grade_submission(submission, form.mark.data, feedback=form.feedback.data, graded_by=current_user.id)
        audit("submission.grade", "submissions", submission.id)
        notify(submission.student_id, "grade", _("صُحّح واجبك"), str(form.mark.data))
        from app.services.email import send_grade_published_email

        send_grade_published_email(submission.student, submission.assignment, form.mark.data)
        flash(_("صُحّح التسليم."), "success")
    return redirect(
        url_for(
            "grades.assignment_detail", class_id=submission.assignment.class_id, assignment_id=submission.assignment_id
        )
    )


@bp.get("/<int:class_id>/gradebook")
@class_access_required
def gradebook(class_id, class_room=None):
    can_teach = can_teach_class(class_room, current_user)
    if current_user.role == UserRole.student:
        categories, items, entries = student_gradebook(current_user.id, class_id)
        return render_template(
            "grades/gradebook_student.html", class_room=class_room, categories=categories, items=items, entries=entries
        )
    categories = list_categories(class_id)
    items = GradeItem.query.filter_by(class_id=class_id).order_by(GradeItem.id.asc()).all()
    members = _students(class_id)
    from app.models.gradebook import GradeEntry

    entries = {}
    if items:
        rows = GradeEntry.query.filter(GradeEntry.grade_item_id.in_([i.id for i in items])).all()
        entries = {(r.student_id, r.grade_item_id): r for r in rows}
    return render_template(
        "grades/gradebook.html",
        class_room=class_room,
        categories=categories,
        items=items,
        members=members,
        entries=entries,
        can_teach=can_teach,
        category_form=CategoryForm(),
        item_form=GradeItemForm(),
    )


@bp.post("/<int:class_id>/categories")
@class_teach_required
def category_create(class_id, class_room=None):
    form = CategoryForm()
    if form.validate_on_submit():
        create_category(class_id, form.name.data, weight=form.weight.data)
        flash(_("أُضيف القسم."), "success")
    return redirect(url_for("grades.gradebook", class_id=class_id))


@bp.post("/categories/<int:category_id>/items")
@login_required
def grade_item_create(category_id):
    from app.models.gradebook import GradeCategory

    category = GradeCategory.query.get_or_404(category_id)
    class_room = _class_or_404(category.class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    form = GradeItemForm()
    if form.validate_on_submit():
        create_grade_item(category, form.title.data, max_mark=form.max_mark.data, kind=form.kind.data)
        flash(_("أُضيف البند."), "success")
    return redirect(url_for("grades.gradebook", class_id=class_room.id))


@bp.post("/items/<int:item_id>/grade")
@login_required
def grade_set(item_id):
    item = GradeItem.query.get_or_404(item_id)
    class_room = _class_or_404(item.class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    student_id = request.form.get("student_id", type=int)
    mark = request.form.get("mark", type=float)
    if student_id and mark is not None:
        set_grade(student_id, item, mark, recorded_by=current_user.id)
        flash(_("سُجّلت الدرجة."), "success")
    return redirect(url_for("grades.gradebook", class_id=class_room.id))


@bp.get("/<int:class_id>/attendance")
@class_access_required
def attendance(class_id, class_room=None):
    day = request.args.get("date", type=date.fromisoformat) or date.today()
    records = get_attendance(class_id, day)
    members = _students(class_id)
    days = attendance_days(class_id)
    return render_template(
        "grades/attendance.html",
        class_room=class_room,
        members=members,
        records=records,
        day=day,
        days=days,
        can_teach=can_teach_class(class_room, current_user),
    )


@bp.post("/<int:class_id>/attendance")
@class_teach_required
def attendance_save(class_id, class_room=None):
    day = request.args.get("date", type=date.fromisoformat) or date.today()
    records = {}
    for member in _students(class_id):
        status = request.form.get(f"status_{member.user_id}")
        if status in ("present", "absent", "late", "excused"):
            records[member.user_id] = status
    if records:
        record_attendance(class_id, day, records, recorded_by=current_user.id)
        audit("attendance.mark", "attendance", class_id, {"date": str(day)})
        flash(_("سُجّل الحضور."), "success")
    return redirect(url_for("grades.attendance", class_id=class_id, date=day.isoformat()))


# ======================================================================
# كشوف الدرجات
# ======================================================================
@bp.get("/<int:class_id>/report-card/<int:student_id>")
@login_required
def report_card(class_id, student_id):
    class_room = _class_or_404(class_id)
    if not can_view_class(class_room, current_user):
        abort(403)
    if current_user.role == UserRole.student and current_user.id != student_id:
        abort(403)
    from app.services.report_card import generate_report_card

    data = generate_report_card(student_id, class_id)
    return render_template("grades/report_card.html", **data)


@bp.get("/<int:class_id>/report-card/<int:student_id>/pdf")
@login_required
def report_card_pdf(class_id, student_id):
    class_room = _class_or_404(class_id)
    if not can_view_class(class_room, current_user):
        abort(403)
    if current_user.role == UserRole.student and current_user.id != student_id:
        abort(403)
    if current_user.role == UserRole.parent:
        from app.services.family import is_parent_of
        if not is_parent_of(current_user.id, student_id):
            abort(403)
    from app.services.report_card import render_report_card_pdf
    from flask import Response

    pdf = render_report_card_pdf(student_id, class_id)
    if pdf is None:
        flash(_("تعذر إنشاء ملف PDF. تأكد من تثبيت xhtml2pdf."), "danger")
        return redirect(url_for("grades.report_card", class_id=class_id, student_id=student_id))
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename=report_card_{student_id}.pdf"},
    )


# ======================================================================
# معايير التقييم (Rubric)
# ======================================================================
@bp.get("/<int:class_id>/rubric/new")
@class_teach_required
def rubric_new(class_id, class_room=None):
    from app.services.rubric import list_rubric_templates

    templates = list_rubric_templates(current_user.id)
    return render_template("grades/rubric_builder.html", class_id=class_id, templates=templates)


@bp.post("/<int:class_id>/rubric")
@class_teach_required
def rubric_create(class_id, class_room=None):
    from app.services.rubric import create_rubric_template

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    criteria = []
    i = 0
    while True:
        ct = request.form.get(f"criteria[{i}][title]")
        if ct is None:
            break
        cs = request.form.get(f"criteria[{i}][max_score]", type=float)
        cd = request.form.get(f"criteria[{i}][description]", "")
        if ct.strip() and cs is not None:
            criteria.append({"title": ct.strip(), "max_score": cs, "description": cd or None})
        i += 1
    if not title:
        flash(_("اسم القالب مطلوب."), "danger")
    elif not criteria:
        flash(_("أضف معياراً واحداً على الأقل."), "danger")
    else:
        create_rubric_template(current_user.id, class_room.school_id, title, description, criteria)
        flash(_("تم حفظ القالب."), "success")
    return redirect(url_for("grades.rubric_new", class_id=class_id))


@bp.get("/rubric/<int:template_id>/grade/<int:submission_id>")
@login_required
def rubric_grade(template_id, submission_id):
    from app.models.gradebook import Submission
    from app.services.rubric import get_rubric_grades, get_rubric_template

    submission = Submission.query.get_or_404(submission_id)
    class_room = _class_or_404(submission.assignment.class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    template = get_rubric_template(template_id)
    if not template:
        abort(404)
    existing = get_rubric_grades(submission_id)
    existing_grades = {g.criterion_id: g.score for g in existing}
    existing_comments = {g.criterion_id: g.comment or "" for g in existing}
    return render_template(
        "grades/rubric_grade.html",
        class_id=class_room.id,
        submission=submission,
        template=template,
        existing_grades=existing_grades,
        existing_comments=existing_comments,
    )


@bp.post("/rubric/grade/<int:submission_id>")
@login_required
def rubric_grade_save(submission_id):
    from app.models.gradebook import Submission
    from app.services.rubric import grade_with_rubric

    submission = Submission.query.get_or_404(submission_id)
    class_room = _class_or_404(submission.assignment.class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    grades = []
    for key, val in request.form.items():
        if key.startswith("score_"):
            cid = int(key.split("_", 1)[1])
            score = float(val) if val else 0
            comment = request.form.get(f"comment_{cid}", "")
            grades.append({"criterion_id": cid, "score": score, "comment": comment or None})
    if grades:
        grade_with_rubric(submission_id, grades, current_user.id)
        flash(_("تم حفظ التقييم."), "success")
    return redirect(url_for("grades.assignment_detail", class_id=class_room.id, assignment_id=submission.assignment_id))


# ======================================================================
# اعتراضات الدرجات
# ======================================================================
@bp.get("/<int:class_id>/appeals")
@class_teach_required
def appeals_list(class_id, class_room=None):
    from app.services.grade_appeals import get_class_appeals

    appeals = get_class_appeals(class_id)
    return render_template("grades/appeals_queue.html", class_room=class_room, appeals=appeals)


@bp.post("/submissions/<int:submission_id>/appeal")
@login_required
def appeal_submit(submission_id):
    from app.models.gradebook import Submission
    from app.services.grade_appeals import submit_appeal

    submission = Submission.query.get_or_404(submission_id)
    if current_user.id != submission.student_id:
        abort(403)
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash(_("اكتب سبب الاعتراض."), "danger")
    else:
        appeal = submit_appeal(submission.id, current_user.id, reason)
        if appeal:
            flash(_("تم إرسال الاعتراض."), "success")
        else:
            flash(_("لديك اعتراض مسبق على هذا التسليم."), "warning")
    class_id = submission.assignment.class_id
    return redirect(url_for("grades.assignment_detail", class_id=class_id, assignment_id=submission.assignment_id))


@bp.post("/appeals/<int:appeal_id>/review")
@login_required
def appeal_review(appeal_id):
    from app.models.gradebook import GradeAppeal
    from app.services.grade_appeals import review_appeal

    appeal = GradeAppeal.query.get_or_404(appeal_id)
    class_room = _class_or_404(appeal.submission.assignment.class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    action = request.form.get("action")
    response = request.form.get("response", "").strip()
    if action in ("approved", "rejected"):
        review_appeal(appeal_id, action, response or None, current_user.id)
        flash(_("تم تحديث الاعتراض."), "success")
    return redirect(url_for("grades.appeals_list", class_id=class_room.id))
