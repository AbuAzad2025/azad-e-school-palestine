"""مسارات الاشتراكات والدفع اليدوي"""

from app.core import role_required
from app.models.billing import ManualPayment, Subscription
from app.models.class_room import ClassRoom
from app.models.user import UserRole
from app.services.access import can_teach_class, can_view_class
from app.services.billing import (
    approve_payment,
    create_plan,
    expire_subscriptions,
    get_plan,
    list_plans,
    list_subscriptions,
    pending_payments,
    record_manual_payment,
    reject_payment,
    subscribe,
)
from app.services.communication import audit, notify
from flask import abort, flash, redirect, render_template, url_for
from flask_babel import _
from flask_login import current_user, login_required

from . import bp
from .forms import PaymentForm, PlanForm, SubscribeForm


def _class_or_404(class_id):
    class_room = ClassRoom.query.filter_by(id=class_id, deleted_at=None).first()
    if not class_room:
        abort(404)
    return class_room


@bp.get("/<int:class_id>")
@login_required
def class_billing(class_id):
    class_room = _class_or_404(class_id)
    if not can_view_class(class_room, current_user):
        abort(403)
    expire_subscriptions()
    plans = list_plans(class_id=class_id)
    my_sub = None
    if current_user.role == UserRole.student:
        subs = list_subscriptions(user_id=current_user.id, class_id=class_id)
        my_sub = subs[0] if subs else None
    return render_template(
        "billing/class_billing.html",
        class_room=class_room,
        plans=plans,
        my_sub=my_sub,
        can_teach=can_teach_class(class_room, current_user),
        plan_form=PlanForm(),
        sub_form=SubscribeForm(),
        pay_form=PaymentForm(),
    )


@bp.post("/<int:class_id>/plans")
@login_required
def plan_create(class_id):
    class_room = _class_or_404(class_id)
    if not can_teach_class(class_room, current_user):
        abort(403)
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
            audit("billing.plan", "subscription_plans", plan.id, amount=plan.price, currency=plan.currency)
            flash(_("حُفظت الخطة."), "success")
    return redirect(url_for("billing.class_billing", class_id=class_id))


@bp.post("/<int:class_id>/subscribe")
@login_required
def subscribe_route(class_id):
    class_room = _class_or_404(class_id)
    if not can_view_class(class_room, current_user):
        abort(403)
    if current_user.role != UserRole.student:
        abort(403)
    form = SubscribeForm()
    if form.validate_on_submit():
        plan = get_plan(form.plan_id.data)
        if not plan or (plan.class_id not in (None, class_id)):
            flash(_("خطة غير صالحة."), "danger")
        else:
            sub, error = subscribe(current_user.id, plan, class_id)
            if error:
                flash(_(error), "danger")
            elif sub is not None:
                audit(
                    "billing.subscribe",
                    "subscriptions",
                    sub.id,
                    amount=sub.price,
                    currency=sub.currency,
                    subscription_id=sub.id,
                )
                flash(_("أُنشئ اشتراكك. أرسل الدفع لتفعيله."), "success")
    return redirect(url_for("billing.class_billing", class_id=class_id))


@bp.post("/subscriptions/<int:subscription_id>/pay")
@login_required
def payment_create(subscription_id):
    sub = Subscription.query.get_or_404(subscription_id)
    class_room = _class_or_404(sub.class_id)
    if not can_view_class(class_room, current_user):
        abort(403)
    if sub.user_id != current_user.id:
        abort(403)
    form = PaymentForm()
    if form.validate_on_submit():
        payment, error = record_manual_payment(
            sub,
            reference=form.reference.data,
            amount=form.amount.data,
            note=form.note.data,
            receipt_file=form.receipt.data,
        )
        if error:
            flash(_(error), "danger")
        elif payment is not None:
            audit(
                "billing.payment",
                "manual_payments",
                payment.id,
                amount=payment.amount,
                currency=sub.currency,
                gateway="manual",
                subscription_id=sub.id,
            )
            flash(_("أُرسل الدفع للاعتماد اليدوي."), "success")
    return redirect(url_for("billing.class_billing", class_id=class_room.id))


@bp.get("/admin")
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin)
def admin():
    expire_subscriptions()
    payments = pending_payments()
    return render_template("billing/admin.html", payments=payments)


@bp.post("/payments/<int:payment_id>/<result>")
@login_required
@role_required(UserRole.super_admin, UserRole.school_admin)
def review(payment_id, result):
    payment = ManualPayment.query.get_or_404(payment_id)
    if result == "approve":
        sub = approve_payment(payment, reviewer_id=current_user.id)
        notify(sub.user_id, "subscription", _("فعّل اشتراكك"), str(sub.end_at))
        from app.services.email import send_payment_approved_email

        send_payment_approved_email(payment)
        audit(
            "billing.approve",
            "subscriptions",
            sub.id,
            amount=payment.amount,
            currency=sub.currency,
            gateway="manual",
            subscription_id=sub.id,
        )
        flash(_("اعتُمد الدفع وفُعّل الاشتراك."), "success")
    elif result == "reject":
        reject_payment(payment, reviewer_id=current_user.id)
        notify(payment.subscription.user_id, "subscription", _("رُفض دفعك — راجع البيانات."))
        from app.services.email import send_payment_rejected_email

        send_payment_rejected_email(payment)
        audit(
            "billing.reject",
            "manual_payments",
            payment.id,
            amount=payment.amount,
            currency=payment.subscription.currency,
            gateway="manual",
            subscription_id=payment.subscription_id,
        )
        flash(_("رُفض الدفع."), "warning")
    else:
        abort(404)
    return redirect(url_for("billing.admin"))


# ======================================================================
# الفواتير
# ======================================================================
@bp.get("/invoices/<int:subscription_id>")
@login_required
def invoice_view(subscription_id):
    sub = Subscription.query.get_or_404(subscription_id)
    class_room = _class_or_404(sub.class_id)
    if not can_view_class(class_room, current_user):
        abort(403)
    from app.services.billing import subscription_payment_summary
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
    sub = Subscription.query.get_or_404(subscription_id)
    class_room = _class_or_404(sub.class_id)
    if not can_view_class(class_room, current_user):
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
