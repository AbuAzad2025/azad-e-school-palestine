"""مسارات المحتوى: دروس + وحدات + مرفقات (وصول مقيّد بأعضاء الصف)"""

from app.core import TxError
from app.models.content import LessonAttachment
from app.services.access import can_teach_class, can_view_class
from app.services.communication import audit
from app.services.content import (
    add_attachment,
    add_youtube,
    create_lesson,
    create_unit,
    delete_attachment,
    get_lesson,
    import_lesson,
    list_lessons,
    list_units,
    publish_lesson,
    shared_lessons,
    unpublish_lesson,
    update_lesson,
)
from flask import abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_babel import _
from flask_login import current_user, login_required

from . import bp
from .forms import AttachmentForm, LessonForm, UnitForm, YoutubeForm


def _class_or_404(class_id):
    from app.models.class_room import ClassRoom

    class_room = ClassRoom.query.filter_by(id=class_id, deleted_at=None).first()
    if not class_room:
        abort(404)
    return class_room


@bp.get("/<int:class_id>/lessons")
@login_required
def class_lessons(class_id):
    class_room = _class_or_404(class_id)
    if not can_view_class(class_room, current_user):
        abort(403)
    return render_template(
        "content/lessons.html",
        class_room=class_room,
        units=list_units(class_id),
        lessons=list_lessons(class_id),
        can_teach=can_teach_class(class_room, current_user),
    )


@bp.get("/<int:class_id>/lessons/new")
@login_required
def lesson_new(class_id):
    class_room = _class_or_404(class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    form = LessonForm()
    form.unit_id.choices = [(u.id, u.title) for u in list_units(class_id)]
    return render_template("content/lesson_form.html", class_room=class_room, form=form, lesson=None)


@bp.post("/<int:class_id>/lessons")
@login_required
def lesson_create(class_id):
    class_room = _class_or_404(class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    form = LessonForm()
    form.unit_id.choices = [(u.id, u.title) for u in list_units(class_id)]
    if form.validate_on_submit():
        lesson, error = create_lesson(
            class_id=class_id,
            title=form.title.data,
            unit_id=form.unit_id.data or None,
            body_html=form.body_html.data,
            created_by=current_user.id,
        )
        if error:
            flash(_(error), "danger")
        elif lesson is not None:
            audit("lesson.create", "lessons", lesson.id)
            flash(_("تم إنشاء الدرس."), "success")
            return redirect(url_for("content.lesson_detail", class_id=class_id, lesson_id=lesson.id))
    return render_template("content/lesson_form.html", class_room=class_room, form=form, lesson=None)


@bp.route("/<int:class_id>/lessons/<int:lesson_id>", methods=["GET", "POST"])
@login_required
def lesson_detail(class_id, lesson_id):
    class_room = _class_or_404(class_id)
    if not can_view_class(class_room, current_user):
        abort(403)
    lesson = get_lesson(lesson_id)
    if not lesson or lesson.class_id != class_id:
        abort(404)
    can_teach = can_teach_class(class_room, current_user)
    if can_teach:
        form = LessonForm(obj=lesson)
        form.unit_id.choices = [(0, _("بلا وحدة"))] + [(u.id, u.title) for u in list_units(class_id)]
        if form.validate_on_submit():
            update_lesson(
                lesson, title=form.title.data, unit_id=form.unit_id.data or None, body_html=form.body_html.data
            )
            flash(_("تم حفظ الدرس."), "success")
            return redirect(url_for("content.lesson_detail", class_id=class_id, lesson_id=lesson.id))
        att_form = AttachmentForm()
        yt_form = YoutubeForm()
        return render_template(
            "content/lesson_detail.html",
            class_room=class_room,
            lesson=lesson,
            can_teach=can_teach,
            form=form,
            att_form=att_form,
            yt_form=yt_form,
        )
    return render_template(
        "content/lesson_detail.html",
        class_room=class_room,
        lesson=lesson,
        can_teach=False,
        form=None,
        att_form=None,
        yt_form=None,
    )


@bp.post("/<int:class_id>/lessons/<int:lesson_id>/publish")
@login_required
def lesson_publish(class_id, lesson_id):
    class_room = _class_or_404(class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    lesson = get_lesson(lesson_id)
    if not lesson:
        abort(404)
    if lesson.status == "published":
        unpublish_lesson(lesson)
        flash(_("أُعيد الدرس للمسودة."), "info")
    else:
        publish_lesson(lesson)
        flash(_("نُشر الدرس."), "success")
    return redirect(url_for("content.lesson_detail", class_id=class_id, lesson_id=lesson_id))


@bp.post("/<int:class_id>/units")
@login_required
def unit_create(class_id):
    class_room = _class_or_404(class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    form = UnitForm()
    if form.validate_on_submit():
        create_unit(class_id, form.title.data)
        flash(_("أُضيفت الوحدة."), "success")
    return redirect(url_for("content.class_lessons", class_id=class_id))


@bp.post("/<int:class_id>/lessons/<int:lesson_id>/attachments")
@login_required
def attachment_upload(class_id, lesson_id):
    class_room = _class_or_404(class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    lesson = get_lesson(lesson_id)
    if not lesson:
        abort(404)
    form = AttachmentForm()
    if form.validate_on_submit():
        try:
            add_attachment(lesson, form.file.data, title=form.title.data)
            flash(_("تم رفع المرفق."), "success")
        except TxError as exc:
            flash(_(str(exc)), "danger")
    return redirect(url_for("content.lesson_detail", class_id=class_id, lesson_id=lesson_id))


@bp.post("/<int:class_id>/lessons/<int:lesson_id>/youtube")
@login_required
def attachment_youtube(class_id, lesson_id):
    class_room = _class_or_404(class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    lesson = get_lesson(lesson_id)
    if not lesson:
        abort(404)
    form = YoutubeForm()
    if form.validate_on_submit():
        add_youtube(lesson, form.url.data, title=form.title.data)
        flash(_("أُضيف الفيديو."), "success")
    return redirect(url_for("content.lesson_detail", class_id=class_id, lesson_id=lesson_id))


@bp.post("/attachments/<int:att_id>/delete")
@login_required
def attachment_delete(att_id):
    att = LessonAttachment.query.get_or_404(att_id)
    class_room = _class_or_404(att.lesson.class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
    delete_attachment(att)
    flash(_("حُذف المرفق."), "success")
    return redirect(url_for("content.lesson_detail", class_id=att.lesson.class_id, lesson_id=att.lesson_id))


@bp.get("/attachments/<int:att_id>/download")
@login_required
def attachment_download(att_id):
    att = LessonAttachment.query.get_or_404(att_id)
    class_room = _class_or_404(att.lesson.class_id)
    if not can_view_class(class_room, current_user):
        abort(403)
    if not att.stored_name:
        abort(404)
    folder = (current_app.config["UPLOAD_FOLDER"] / att.stored_name).parent
    return send_from_directory(
        folder,
        att.stored_name.rsplit("/", 1)[-1],
        as_attachment=True,
        download_name=att.original_name or att.stored_name,
    )


@bp.get("/shared")
@login_required
def shared_library():
    from app.core.tenancy import current_school_id
    from app.models.school import Subject

    school_id = current_school_id()
    if not school_id:
        flash(_("لا توجد مدرسة مرتبطة بحسابك."), "warning")
        return redirect(url_for("auth.dashboard"))
    subject_id = request.args.get("subject_id", type=int)
    lessons = shared_lessons(school_id, subject_id)
    subjects = Subject.query.all()
    return render_template(
        "content/shared_library.html",
        lessons=lessons,
        subjects=subjects,
        selected_subject=subject_id,
    )


@bp.post("/import/<int:lesson_id>")
@login_required
def lesson_import(lesson_id):
    from app.models.class_room import ClassRoom
    from app.services.access import can_teach_class

    target_class_id = request.args.get("target_class_id", type=int) or request.form.get("target_class_id", type=int)
    if not target_class_id:
        flash(_("يرجى تحديد الصف الهدف."), "danger")
        return redirect(url_for("content.shared_library"))

    target_class = ClassRoom.query.filter_by(id=target_class_id, deleted_at=None).first()
    if not target_class or not can_teach_class(target_class, current_user):
        abort(403)

    new_lesson, error = import_lesson(lesson_id, target_class_id, current_user.id)
    if error:
        flash(_(error), "danger")
    else:
        assert new_lesson is not None
        audit("lesson.import", "lessons", new_lesson.id)
        flash(_("تم استيراد الدرس بنجاح."), "success")
        return redirect(url_for("content.lesson_detail", class_id=target_class_id, lesson_id=new_lesson.id))
    return redirect(url_for("content.shared_library"))


# === وضع عدم الاتصال ===


@bp.get("/offline")
@login_required
def offline_downloads():
    from app.services.offline import get_offline_items

    items = get_offline_items(current_user.id)
    return render_template("content/offline_downloads.html", items=items)


@bp.post("/offline/mark")
@login_required
def mark_offline():
    from app.services.offline import mark_for_download

    attachment_id = request.form.get("attachment_id", type=int)
    lesson_id = request.form.get("lesson_id", type=int)
    if not attachment_id or not lesson_id:
        flash(_("بيانات ناقصة"), "danger")
        return redirect(url_for("content.offline_downloads"))
    result = mark_for_download(current_user.id, attachment_id, lesson_id)
    if result:
        flash(_("تم التحديد للتنزيل"), "success")
    else:
        flash(_("المرفق محدد للتنزيل مسبقاً"), "warning")
    return redirect(url_for("content.offline_downloads"))


@bp.post("/offline/<int:download_id>/remove")
@login_required
def remove_offline(download_id):
    from app.models.offline import OfflineDownload
    from app.services.offline import remove_offline as _remove_offline

    download = OfflineDownload.query.get_or_404(download_id)
    if download.student_id != current_user.id:
        abort(403)

    _remove_offline(download_id)
    flash(_("تم الإزالة"), "success")
    return redirect(url_for("content.offline_downloads"))
