"""مسارات الاشتراكات والدفع اليدوي"""

from app.core import class_teach_required, flash_error, role_required
from app.core.db import TxError
from app.extensions import db
from app.models.billing import ManualPayment, PaymentReceipt, Subscription
from app.models.class_room import ClassRoom
from app.models.user import UserRole
from app.services.access import can_pay_class, can_teach_class
from app.services.billing import (
    approve_payment,
    create_discount_code,
    create_plan,
    get_plan,
    list_plans,
    list_subscriptions,
    pending_payments,
    record_manual_payment,
    reject_payment,
    subscribe,
    subscription_payment_summary,
    validate_discount_code,
)
from app.services.communication import audit, notify
from app.services.family import is_parent_of, list_children
from app.services.schools import is_member
from flask import abort, flash, redirect, render_template, url_for
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy import or_

from . import bp
from .forms import DiscountCodeForm, PaymentForm, PlanForm, SubscribeForm, ValidateDiscountForm


def _linked_children_ids() -> list[int]:
    """أبناء وليّ الأمر الحالي المرتبطون برابط نشط (AZ-P0-03)."""
    if current_user.role != UserRole.parent:
        return []
    return [link.student_id for link in list_children(current_user.id)]


def _class_payee(class_room):
    """صاحب الاشتراك الذي تُعرض دفعته في هذه الصفحة — الطالب نفسه أو ابن وليّ الأمر (
    AZ-P0-03).

    الأهلية نفسها التي أفحصها ``can_pay_class``: اشتراكات الأبناء المرتبطين في
    هذا الصف فقط — طلب طالب غير مرتبط لا يفتح الباب، وفلترة ``user_id``
    تبقى في ``WHERE`` فلا بعث أي رسالة أخرى تحت سياق هذا الطلب.
    """
    if current_user.role == UserRole.student:
        return current_user
    student_ids = _linked_children_ids()
    if not student_ids:
        return None
    sub = (
        Subscription.query.filter(Subscription.user_id.in_(student_ids), Subscription.class_id == class_room.id)
        .order_by(Subscription.created_at.asc())
        .first()
    )
    return sub.user if sub is not None else None


def _invoice_can_view(class_room, sub) -> bool:
    """مالك الاشتراك نفسه، أو وليّ أمر مرتبط به رابط نشط (AZ-P0-03)."""
    if is_member(class_room, current_user):
        return True
    return current_user.role == UserRole.parent and is_parent_of(current_user.id, sub.user_id)


def _payment_scope_or_403(payment: ManualPayment) -> None:
    """يمنع مشرف مدرسة من مراجعة دفعة/إيصال مدرسة أخرى via ID.

    super_admin فوق التينانتس؛ غيره يُقارَن بمدرسته الفعّالة. الرفض 403 لا 404
    لأن الصفّ موجود فعلاً، فلا نكشفه ولا نسمح بتعديله.
    """
    if current_user.role == UserRole.super_admin:
        return
    from app.core.tenancy import current_school_id

    sub = payment.subscription
    class_room = sub.class_room if sub is not None else None
    if class_room is None or class_room.school_id != current_school_id():
        abort(403)


def _class_or_404(class_id):
    class_room = ClassRoom.query.filter_by(id=class_id, deleted_at=None).first()
    if not class_room:
        # RLS يخفي صفّ مدرسة أخرى قبل فحص الصلاحية؛ الرفض 403 بقراءة مرفوعة
        # مقيّدة (انظر access_read_scope في app/core/rls.py) لا 404.
        from app.core.rls import get_for_access_check

        if get_for_access_check(ClassRoom, class_id) is not None:
            abort(403)
        abort(404)
    return class_room


@bp.get("/<int:class_id>")
@login_required
def class_billing(class_id):
    # P3-15: انتهاء الاشتراكات انتقل لمهمة CLI دورية (flask expire-subscriptions)
    # AZ-P0-01: الحارس هنا can_pay_class لا can_view_class — صاحب اشتراك
    # معلّق (لا عضوية فعّالة) يجب أن يفتح صفحة الدفع لإكمال الحلقة.
    # AZ-P0-03: وليّ الأمر المرتبط يفتح صفحة الدفع لصفّ ابنه (ذراع الوالد في
    # can_pay_class) — المحتوى التعليمي يبقى للطالب، فيلاصق P-SEC-13.
    class_room = _class_or_404(class_id)
    if not can_pay_class(class_room, current_user):
        abort(403)
    plans = list_plans(class_id=class_id)
    payee = _class_payee(class_room)
    my_sub = None
    if payee is not None:
        subs = list_subscriptions(user_id=payee.id, class_id=class_id)
        my_sub = subs[0] if subs else None
    return render_template(
        "billing/class_billing.html",
        class_room=class_room,
        plans=plans,
        my_sub=my_sub,
        payee=payee,
        children=list_children(current_user.id) if current_user.role == UserRole.parent else [],
        can_teach=can_teach_class(class_room, current_user),
        plan_form=PlanForm(),
        sub_form=SubscribeForm(),
        pay_form=PaymentForm(),
    )


@bp.post("/<int:class_id>/plans")
@class_teach_required
def plan_create(class_id, class_room=None):
    form = PlanForm()
    if form.validate_on_submit():
        plan, error = create_plan(
            school_id=class_room.school_id,
            class_id=class_id,
            name=form.name.data,
            plan=form.plan.data,
            price=form.price.data,
            currency=form.currency.data,
            duration_days=form.duration_days.data,
        )
        if error:
            flash(_(error), "danger")
        elif plan is not None:
            audit("billing.plan", "subscription_plans", plan.id, amount=float(plan.price), currency=plan.currency)
            flash(_("حُفظت الخطة."), "success")
    return redirect(url_for("billing.class_billing", class_id=class_id))


def _resolve_payee(class_room, form) -> tuple[int | None, int | None]:
    """(صاحب الاشتراك، الدافع) من دور الفاعل وصيغة الطلب — أو رفض بـ None.

    الطالب: اشتراكه هو بعد جواز عضوية الصف (حاجز ``is_member`` السابق
    يبقى كله). وليّ الأمر: ``student_id`` من الصيغة، والمرفوض إن لم يكن
    مرتبطاً به رابط نشط — التحقق عبر ``is_parent_of`` مباشرة لا عبر
    معرّف مُعاد من نتيجة معرفية أخرى (AZ-P0-03). غير المرتبط — وسيطاً
    أي دور آخر — يعيد None فترفع مساراتها 403.
    """
    if current_user.role == UserRole.student:
        if not is_member(class_room, current_user):
            return None, None
        return current_user.id, None
    if current_user.role == UserRole.parent:
        student_id = form.student_id.data
        if student_id is None or not is_parent_of(current_user.id, student_id):
            return None, None
        return student_id, current_user.id
    return None, None


@bp.post("/<int:class_id>/subscribe")
@login_required
def subscribe_route(class_id, class_room=None):
    class_room = _class_or_404(class_id)
    # AZ-P0-03: الدافع طالب (اشتراكه هو) أو وليّ أمر مرتبط (دفعاً عن ابنه).
    # أي دور آخر — أو وليّ أمر غير مرتبط بالطالب المُمرَّر — 403.
    form = SubscribeForm()
    payee_id, payer_id = _resolve_payee(class_room, form)
    if payee_id is None:
        abort(403)
    # نفس شرط فتح صفحة الدفع: وليّ الأمر لا يشترك لابنه في صف لا صلة لهما به
    # عبر تمرير class_id من خارج الواجهة. حاجز الطالب (العضوية) داخل
    # _resolve_payee، وهذا الحاجز يغطي ذراع الوالد صراحةً.
    #
    # للوالد فقط: ``can_pay_class`` للطالب تشترط اشتراكاً سابقاً (حتى المعلّق)
    # لأنها صُمِّمت لفتح صفحة الدفع لا لإنشاء أول اشتراك؛ تطبيقها على الطالب
    # كان يمنع أول عملية شراء رغم عضويته في الصف التي فحصها _resolve_payee.
    if current_user.role == UserRole.parent and not can_pay_class(class_room, current_user):
        abort(403)
    if form.validate_on_submit():
        plan = get_plan(form.plan_id.data)
        if not plan or (plan.class_id not in (None, class_id)):
            flash(_("خطة غير صالحة."), "danger")
        else:
            sub, error = subscribe(payee_id, plan, class_id, payer_id=payer_id)
            if error:
                flash(_(error), "danger")
            elif sub is not None:
                audit(
                    "billing.subscribe",
                    "subscriptions",
                    sub.id,
                    amount=float(sub.price),
                    currency=sub.currency,
                    subscription_id=sub.id,
                )
                flash(_("أُنشئ اشتراكك. أرسل الدفع لتفعيله."), "success")
    return redirect(url_for("billing.class_billing", class_id=class_id))


@bp.post("/subscriptions/<int:subscription_id>/pay")
@login_required
def payment_create(subscription_id):
    sub = db.get_or_404(Subscription, subscription_id)
    class_room = _class_or_404(sub.class_id)
    # AZ-P0-01: مالك الاشتراك وحده يمكنه فتح صف الدفع — لا فحوص وسيطة. الدفع
    # دائماً على اشتراك الزائر نفسه فشرط المالك يكفي، والمفتاح العابر
    # (غير المالك) يظل 403 كما سبق، وRLS يخفي اشتراكات المدارس الأخرى بـ 404.
    # AZ-P0-03: المالك نفسه (طالب) أو وليّ أمر مرتبط به — غير المرتبط يظل
    # 403، ولا يُنشأ أي صف دفع (تظهر بعد الحاجز لا قبله).
    payer_id: int | None = None
    if sub.user_id == current_user.id:
        payer_id = None  # الدافع هو المالك نفسه — النموذج السائد يبقى سليماً
    elif current_user.role == UserRole.parent and is_parent_of(current_user.id, sub.user_id):
        payer_id = current_user.id
    else:
        abort(403)
    form = PaymentForm()
    if form.validate_on_submit():
        payment, error = record_manual_payment(
            sub,
            reference=form.reference.data,
            amount=form.amount.data,
            note=form.note.data,
            receipt_file=form.receipt.data,
            payer_id=payer_id,
        )
        if error:
            flash(_(error), "danger")
        elif payment is not None:
            audit(
                "billing.payment",
                "manual_payments",
                payment.id,
                amount=float(payment.amount),
                currency=sub.currency,
                gateway="manual",
                subscription_id=sub.id,
            )
            flash(_("أُرسل الدفع للاعتماد اليدوي."), "success")
    return redirect(url_for("billing.class_billing", class_id=class_room.id))


@bp.get("/payments/receipts/<path:filename>")
@login_required
def payment_file(filename):
    """تنزيل إيصال دفع عبر جدول الإيصالات — لا من مسار قابل للاجتياز.

    الاسم القادم من الرابط يُبحث عنه كصفّ ``PaymentReceipt.stored_name``
    (اسم عشوائي يُولّده ``save_upload``). بهذا لا يُبنى أي مسار من مدخل
    المستخدم، والوصول يُقيَّد بمالك الاشتراك/الدافع/وليّ الأمر/مشرف المدرسة.
    """
    from flask import current_app, send_from_directory

    receipt = PaymentReceipt.query.filter_by(stored_name=filename).first()
    if receipt is None:
        abort(404)
    payment = receipt.payment
    sub = payment.subscription

    allowed = current_user.role == UserRole.super_admin
    if not allowed:
        if current_user.role == UserRole.school_admin:
            from app.core.tenancy import current_school_id

            class_room = sub.class_room if sub is not None else None
            allowed = class_room is not None and class_room.school_id == current_school_id()
        elif sub is not None:
            allowed = current_user.id in {sub.user_id, sub.payer_id, payment.payer_id}
            if not allowed and current_user.role == UserRole.parent:
                allowed = is_parent_of(current_user.id, sub.user_id)
    if not allowed:
        abort(403)

    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        receipt.stored_name,
        as_attachment=True,
        download_name=receipt.original_name or "receipt",
    )


@bp.get("/admin")
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin)
def admin():
    from app.core.tenancy import current_school_id

    school_id = None if current_user.role == UserRole.super_admin else current_school_id()
    if current_user.role != UserRole.super_admin and school_id is None:
        abort(403)
    payments = pending_payments(school_id=school_id)
    return render_template("billing/admin.html", payments=payments)


@bp.post("/payments/<int:payment_id>/<result>")
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin)
def review(payment_id, result):
    payment = db.get_or_404(ManualPayment, payment_id)
    _payment_scope_or_403(payment)
    if result == "approve":
        try:
            sub = approve_payment(payment, reviewer_id=current_user.id)
        except TxError as exc:
            db.session.rollback()
            flash_error(str(exc), "warning")
            return redirect(url_for("billing.admin"))
        notify(sub.user_id, "subscription", _("فعّل اشتراكك"), str(sub.end_at))
        from app.services.email import send_payment_approved_email

        send_payment_approved_email(payment)
        audit(
            "billing.approve",
            "subscriptions",
            sub.id,
            amount=float(payment.amount),
            currency=sub.currency,
            gateway="manual",
            subscription_id=sub.id,
        )
        flash(_("اعتُمد الدفع وفُعّل الاشتراك."), "success")
    elif result == "reject":
        try:
            reject_payment(payment, reviewer_id=current_user.id)
        except TxError as exc:
            db.session.rollback()
            flash_error(str(exc), "warning")
            return redirect(url_for("billing.admin"))
        notify(payment.subscription.user_id, "subscription", _("رُفض دفعك — راجع البيانات."))
        from app.services.email import send_payment_rejected_email

        send_payment_rejected_email(payment)
        audit(
            "billing.reject",
            "manual_payments",
            payment.id,
            amount=float(payment.amount),
            currency=payment.subscription.currency,
            gateway="manual",
            subscription_id=payment.subscription_id,
        )
        flash(_("رُفض الدفع."), "warning")
    else:
        abort(404)
    return redirect(url_for("billing.admin"))


# ======================================================================
# أكواد الخصم (Admin)
# ======================================================================
@bp.get("/discounts")
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin)
def discount_list():
    """قائمة أكواد الخصم."""
    from app.core.tenancy import current_school_id
    from app.models.billing import DiscountCode

    query = DiscountCode.query
    if current_user.role != UserRole.super_admin:
        school_id = current_school_id()
        if school_id is None:
            abort(403)
        # الأكواد العامة (school_id IS NULL) تُطبَّق في مدرسته أيضاً؛ تُعرض
        # للقراءة فقط، وإنشاؤها وتعديلها يبقيان للمشرف الكلي.
        query = query.filter(or_(DiscountCode.school_id == school_id, DiscountCode.school_id.is_(None)))
    discounts = query.order_by(DiscountCode.created_at.desc()).all()
    return render_template("billing/discount_list.html", discounts=discounts)


@bp.route("/discounts/new", methods=["GET", "POST"])
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin)
def discount_create():
    """إنشاء كود خصم جديد.

    مشرف المنصة يُنشئ كوداً عامّاً (``school_id IS NULL``) يُطبَّق في أي
    مدرسة؛ مشرف المدرسة يُنشئ كوداً لمدرسته حصراً. لا قيمة افتراضية للمدرسة
    (كانت ``or 1`` تنسب كود المشرف الكلي إلى المدرسة رقم 1).
    """
    from app.core.tenancy import current_school_id

    form = DiscountCodeForm()
    if form.validate_on_submit():
        school_id: int | None
        if current_user.role == UserRole.super_admin:
            school_id = None
        else:
            school_id = current_school_id()
            if school_id is None:
                abort(403)
        discount, error = create_discount_code(
            school_id=school_id,
            code=form.code.data,
            name=form.name.data,
            type_=form.type.data,
            value=form.value.data,
            max_uses=form.max_uses.data,
            expiry_date=form.expiry_date.data,
        )
        if error:
            flash(_(error), "danger")
        elif discount is not None:
            flash(_("تم إنشاء كود الخصم."), "success")
            return redirect(url_for("billing.discount_list"))
    return render_template("billing/discount_form.html", form=form, editing=False)


# ======================================================================
# التحقق من كود الخصم (AJAX)
# ======================================================================
@bp.post("/validate-code")
@login_required
def validate_code():
    """AJAX endpoint — يتحقق من كود الخصم وإرجاع مبلغ الخصم."""
    form = ValidateDiscountForm()
    if form.validate_on_submit():
        discount, error = validate_discount_code(form.code.data, form.plan_id.data)
        if error:
            return {"discount": None, "error": _(error)}, 400
        return {"discount": discount, "error": None}
    return {"discount": None, "error": _("بيانات غير صالحة")}, 400


# ======================================================================
# الفواتير
# ======================================================================
@bp.get("/invoices/<int:subscription_id>")
@login_required
def invoice_view(subscription_id):
    sub = db.session.get(Subscription, subscription_id)
    if sub is None:
        # اشتراك مدرسة أخرى يخفيه RLS؛ ارفض 403 بقراءة مرفوعة إن وُجد فعلاً.
        from app.core.rls import get_for_access_check

        if get_for_access_check(Subscription, subscription_id) is not None:
            abort(403)
        abort(404)
    class_room = _class_or_404(sub.class_id)
    if not _invoice_can_view(class_room, sub):
        abort(403)
    from app.services.invoice import generate_invoice_number

    summary = subscription_payment_summary(subscription_id)
    invoice_number = generate_invoice_number(sub)
    return render_template(
        "billing/invoice.html",
        subscription=sub,
        summary=summary,
        invoice_number=invoice_number,
    )


@bp.get("/invoices/<int:subscription_id>/pdf")
@login_required
def invoice_pdf(subscription_id):
    sub = db.session.get(Subscription, subscription_id)
    if sub is None:
        from app.core.rls import get_for_access_check

        if get_for_access_check(Subscription, subscription_id) is not None:
            abort(403)
        abort(404)
    class_room = _class_or_404(sub.class_id)
    if not _invoice_can_view(class_room, sub):
        abort(403)
    from app.services.invoice import render_invoice_pdf
    from flask import Response

    pdf = render_invoice_pdf(subscription_id)
    if pdf is None:
        flash(_("تعذر إنشاء ملف PDF."), "danger")
        return redirect(url_for("billing.invoice_view", subscription_id=subscription_id))
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename=invoice_{subscription_id}.pdf"},
    )
