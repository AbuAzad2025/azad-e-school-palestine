"""مسارات المدارس والصفوف"""

from app.core import role_required
from app.core.tenancy import current_school_id, get_school_or_404
from app.models.school import Grade
from app.models.user import UserRole
from app.services.communication import audit
from app.services.schools import (
    add_grade,
    create_class,
    create_school_with_defaults,
    get_class_members,
    get_or_create_subject,
    is_member,
    join_class,
    list_classes,
    list_schools,
    regenerate_join_code,
)
from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload, selectinload

from . import bp
from .forms import AssignTeacherForm, ClassForm, GradeForm, JoinClassForm, SchoolForm


def _school_id_or_abort():
    sid = current_school_id()
    if not sid:
        abort(403)
    return sid


@bp.get("/")
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin)
def index():
    return render_template("schools/index.html", schools=list_schools())


@bp.route("/new", methods=["GET", "POST"])
@login_required
@role_required(UserRole.super_admin)
def create():
    form = SchoolForm()
    if form.validate_on_submit():
        school, error = create_school_with_defaults(form.name_ar.data, form.domain.data)
        if error:
            flash(_(error), "danger")
        elif school is not None:
            audit("school.create", "schools", school.id)
            flash(_("تم إنشاء المدرسة."), "success")
            return redirect(url_for("schools.manage", school_id=school.id))
    return render_template("schools/form.html", form=form, title=_("مدرسة جديدة"))


@bp.get("/<int:school_id>/manage")
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin)
def manage(school_id):
    school = get_school_or_404(school_id)
    return render_template(
        "schools/manage.html",
        school=school,
        classes=list_classes(school_id),
        grade_form=GradeForm(),
    )


@bp.route("/<int:school_id>/classes/new", methods=["GET", "POST"])
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin, UserRole.teacher)
def class_new(school_id):
    school = get_school_or_404(school_id)
    form = ClassForm()
    grades = Grade.query.filter_by(school_id=school_id).order_by(Grade.grade_level).all()
    form.grade_id.choices = [(g.id, f"{g.grade_level}") for g in grades] or [(0, _("لا مستويات بعد"))]
    if form.validate_on_submit() and form.grade_id.data:
        subject = get_or_create_subject(form.subject.data)
        class_room, error = create_class(
            school_id=school_id,
            subject_id=subject.id,
            grade_id=form.grade_id.data,
            teacher_id=current_user.id if current_user.role == UserRole.teacher else None,
            semester=form.semester.data,
            name=form.name.data,
            price_first_term=form.price_first_term.data,
            price_second_term=form.price_second_term.data,
            price_annual=form.price_annual.data,
        )
        if error:
            flash(_(error), "danger")
        elif class_room is not None:
            audit("class.create", "classes", class_room.id)
            flash(_("تم إنشاء الصف."), "success")
            return redirect(url_for("schools.class_detail", class_id=class_room.id))
    return render_template("schools/class_form.html", form=form, school=school)


@bp.route("/<int:school_id>/grades", methods=["POST"])
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin)
def grade_add(school_id):
    get_school_or_404(school_id)
    form = GradeForm()
    if form.validate_on_submit():
        add_grade(school_id, form.grade_level.data, form.name_ar.data)
        flash(_("تمت إضافة المستوى."), "success")
    return redirect(url_for("schools.manage", school_id=school_id))


@bp.route("/classes/join", methods=["GET", "POST"])
@login_required
@role_required(UserRole.student, UserRole.parent)
def class_join():
    form = JoinClassForm()
    if form.validate_on_submit():
        from app.models.class_room import ClassRoom

        class_room = ClassRoom.query.filter_by(join_code=form.code.data.strip()).first()
        if not class_room or not class_room.is_active:
            flash(_("رمز انضمام غير صالح."), "danger")
        else:
            error = join_class(class_room, current_user)
            if error:
                flash(_(error), "danger")
            else:
                audit("class.join", "class_members", class_room.id)
                flash(_("تم الانضمام للصف."), "success")
                return redirect(url_for("schools.class_detail", class_id=class_room.id))
    return render_template("schools/join.html", form=form)


@bp.get("/classes")
@login_required
def my_classes():
    from app.models.class_room import ClassMember, ClassRoom
    from sqlalchemy import func

    memberships = (
        ClassMember.query.filter_by(user_id=current_user.id, status="active")
        .options(
            selectinload(ClassMember.class_room).joinedload(ClassRoom.subject),
            selectinload(ClassMember.class_room).joinedload(ClassRoom.grade),
        )
        .all()
    )
    class_ids = [m.class_room.id for m in memberships]
    counts = dict(
        ClassMember.query.filter(ClassMember.class_room_id.in_(class_ids), ClassMember.status == "active")
        .with_entities(ClassMember.class_room_id, func.count())
        .group_by(ClassMember.class_room_id)
        .all()
    )
    for m in memberships:
        m.member_count = counts.get(m.class_room.id, 0)
    return render_template("schools/my_classes.html", memberships=memberships)


@bp.get("/<int:school_id>/classes")
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin)
def school_classes(school_id):
    school = get_school_or_404(school_id)
    return render_template("schools/classes.html", school=school, classes=list_classes(school_id))


@bp.get("/class/<int:class_id>")
@login_required
def class_detail(class_id):

    class_room = db_get_class(class_id)
    if not class_room:
        abort(404)
    # وصول: عضو الصف أو معلم/مشرف المدرسة أو super_admin
    school_ok = current_school_id() == class_room.school_id if current_school_id() else False
    if not (is_member(class_room, current_user) or school_ok or current_user.role == UserRole.super_admin):
        abort(403)
    return render_template(
        "schools/class_detail.html",
        class_room=class_room,
        members=get_class_members(class_room),
    )


def db_get_class(class_id):
    from app.models.class_room import ClassRoom

    return (
        ClassRoom.query.filter_by(id=class_id, deleted_at=None)
        .options(joinedload(ClassRoom.subject), joinedload(ClassRoom.grade), joinedload(ClassRoom.teacher))
        .first()
    )


@bp.post("/class/<int:class_id>/code")
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin, UserRole.teacher)
def class_code(class_id):
    class_room = db_get_class(class_id)
    if not class_room:
        abort(404)
    if current_school_id() != class_room.school_id and current_user.role != UserRole.super_admin:
        abort(403)
    regenerate_join_code(class_room)
    audit("class.code", "classes", class_room.id)
    flash(_("تم توليد رمز جديد."), "success")
    return redirect(url_for("schools.class_detail", class_id=class_room.id))


@bp.post("/class/<int:class_id>/teacher")
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin)
def class_assign_teacher(class_id):
    from app.core import tx
    from app.extensions import db
    from app.models.class_room import ClassRoom
    from app.models.user import User

    class_room = ClassRoom.query.filter_by(id=class_id, deleted_at=None).first()
    if not class_room:
        abort(404)
    if current_school_id() != class_room.school_id and current_user.role != UserRole.super_admin:
        abort(403)
    form = AssignTeacherForm()
    if form.validate_on_submit():
        teacher = db.session.get(User, form.teacher_id.data)
        if teacher and teacher.role == UserRole.teacher:

            def _assign():
                class_room.teacher_id = teacher.id

            tx(_assign)
            audit("class.assign_teacher", "classes", class_room.id)
            flash(_("تم تعيين المعلم."), "success")
    return redirect(url_for("schools.class_detail", class_id=class_room.id))


@bp.get("/onboarding/<int:step>")
@login_required
def onboarding_step(step):
    from app.services.onboarding import get_onboarding_status, get_wizard_steps, start_onboarding

    sid = current_school_id()
    if not sid:
        flash(_("لا توجد مدرسة مرتبطة بحسابك."), "danger")
        return redirect(url_for("main.index"))
    steps = get_wizard_steps()
    start_onboarding(sid)
    status = get_onboarding_status(sid)
    if status["is_complete"]:
        flash(_("تم إعداد المدرسة بالفعل."), "info")
        return redirect(url_for("admin.school_admin_dashboard"))
    from app.services.onboarding import get_onboarding

    progress = get_onboarding(sid)
    data = progress.completed_steps if progress else {}
    return render_template("schools/onboarding.html", steps=steps, current_step=step, data=data)


@bp.post("/onboarding/<int:step>")
@login_required
def onboarding_step_save(step):
    from app.services.onboarding import complete_step

    sid = current_school_id()
    if not sid:
        flash(_("لا توجد مدرسة مرتبطة بحسابك."), "danger")
        return redirect(url_for("main.index"))
    step_data = {}
    for key, val in request.form.items():
        if key != "csrf_token":
            step_data[key] = val
    complete_step(sid, step, step_data)
    if step < 5:
        return redirect(url_for("schools.onboarding_step", step=step + 1))
    flash(_("تم إعداد المدرسة بنجاح!"), "success")
    return redirect(url_for("admin.school_admin_dashboard"))
