"""مسارات الدروس الخصوصية — سوق حر بلا عزل مدرسة"""

from decimal import Decimal

from app.models.tutoring import TutoringRequest, TutoringSession
from app.models.user import User, UserRole
from app.services.communication import audit, notify
from app.services.tutoring import (
    can_access,
    create_request,
    create_tutor_profile,
    find_by_invite_code,
    generate_live_session_url,
    get_profile,
    list_requests_for_student,
    list_requests_for_tutor,
    list_sessions_for,
    respond_request,
    search_tutors,
    update_profile,
    update_session,
    update_session_live_status,
)
from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required

from . import bp
from .forms import BookingForm, PaySessionForm, SessionForm, TutorProfileForm


@bp.get("/")
def index():
    q = request.args.get("q", "")
    tutors = search_tutors(q=q)
    return render_template("tutoring/index.html", tutors=tutors, q=q)


@bp.get("/tutors/<int:tutor_id>")
def profile(tutor_id):
    tutor = User.query.get_or_404(tutor_id)
    prof = get_profile(tutor_id)
    if not prof or not prof.is_active:
        abort(404)
    return render_template("tutoring/profile.html", tutor=tutor, prof=prof)


@bp.get("/invite/<code>")
def invite(code):
    prof = find_by_invite_code(code)
    if not prof or not prof.is_active:
        flash(_("رمز دعوة غير صالح."), "danger")
        return redirect(url_for("tutoring.index"))
    return redirect(url_for("tutoring.profile", tutor_id=prof.tutor_id))


@bp.route("/my", methods=["GET"])
@login_required
def my():
    requests = list_requests_for_tutor(current_user.id) if current_user.role != UserRole.student else []
    student_requests = list_requests_for_student(current_user.id) if current_user.role != UserRole.teacher else []
    as_tutor = list_sessions_for(current_user.id, as_tutor=True)
    as_student = list_sessions_for(current_user.id, as_tutor=False)
    return render_template(
        "tutoring/my.html",
        requests=requests,
        student_requests=student_requests,
        as_tutor=as_tutor,
        as_student=as_student,
    )


@bp.route("/profile/new", methods=["GET", "POST"])
@login_required
def profile_new():
    """يمكن لأي مستخدم إنشاء ملف معلم خصوصي (استثناء تينانتس)."""
    form = TutorProfileForm()
    if form.validate_on_submit():
        prof, error = create_tutor_profile(
            tutor_id=current_user.id,
            subject=form.subject.data,
            price_hour=form.price_hour.data,
            price_session=form.price_session.data,
            mode=form.mode.data,
            bio=form.bio.data,
        )
        if error:
            flash(_(error), "danger")
        elif prof is not None:
            audit("tutoring.profile", "tutor_profiles", prof.id)
            flash(_("تم نشر ملفك. شارك رابط ملفك مع طلابك."), "success")
            return redirect(url_for("tutoring.profile", tutor_id=current_user.id))
    return render_template("tutoring/profile_form.html", form=form, editing=False)


@bp.route("/profile/edit", methods=["GET", "POST"])
@login_required
def profile_edit():
    prof = get_profile(current_user.id)
    if not prof:
        return redirect(url_for("tutoring.profile_new"))
    form = TutorProfileForm(obj=prof)
    if form.validate_on_submit():
        update_profile(
            prof,
            subject=form.subject.data,
            price_hour=form.price_hour.data,
            price_session=form.price_session.data,
            mode=form.mode.data,
            bio=form.bio.data,
        )
        flash(_("تم تحديث الملف."), "success")
        return redirect(url_for("tutoring.profile", tutor_id=current_user.id))
    return render_template("tutoring/profile_form.html", form=form, editing=True)


@bp.route("/book/<int:tutor_id>", methods=["GET", "POST"])
@login_required
def book(tutor_id):
    """يمكن للطلاب فقط حجز دروس خصوصية من المعلمين."""
    if current_user.role != UserRole.student:
        flash(_("حجز الدروس الخصوصية متاح للطلاب فقط. سجّل الدخول بحساب طالب لتتمكن من الحجز."), "warning")
        return redirect(url_for("tutoring.index"))
    tutor = User.query.get_or_404(tutor_id)
    prof = get_profile(tutor_id)
    if not prof or not prof.is_active:
        abort(404)
    if tutor_id == current_user.id:
        flash(_("لا يمكنك حجز درس من نفسك."), "warning")
        return redirect(url_for("tutoring.profile", tutor_id=tutor_id))
    form = BookingForm()
    if form.validate_on_submit():
        # تحقق السعر المقترح مقابل أسعار المعلم المعلنة
        price_quote = form.price_quote.data
        if price_quote is not None:
            tutor_price = prof.price_session if form.mode.data == "online" else prof.price_hour
            if tutor_price is not None:
                tutor_price_decimal = Decimal(str(tutor_price))
                min_allowed = tutor_price_decimal * Decimal("0.8")  # السماح بخصم 20% كحد أدنى
                max_allowed = tutor_price_decimal * Decimal("1.5")  # السماح بزيادة 50% كحد أقصى
                if price_quote < min_allowed or price_quote > max_allowed:
                    flash(_("السعر المقترح خارج النطاق المسموح (80%–150% من سعر المعلم المعلن)."), "danger")
                    return render_template("tutoring/book.html", form=form, tutor=tutor, prof=prof)
        req, error = create_request(
            tutor_id=tutor_id,
            student_id=current_user.id,
            subject=form.subject.data,
            preferred_time=form.preferred_time.data,
            mode=form.mode.data,
            price_quote=price_quote,
            note=form.note.data,
        )
        if error:
            flash(_(error), "danger")
        elif req is not None:
            audit(
                "tutoring.request",
                "tutoring_requests",
                req.id,
                amount=req.price_quote,
                currency="ILS",
                session_id=req.id,
            )
            notify(tutor_id, "tutoring", _("طلب درس خصوصي جديد"), f"{current_user.name_ar}: {form.subject.data}")
            flash(_("أُرسل طلبك للمعلم. سيعاودك بالرد."), "success")
            return redirect(url_for("tutoring.my"))
    return render_template("tutoring/book.html", form=form, tutor=tutor, prof=prof)


@bp.post("/requests/<int:req_id>/respond/<result>")
@login_required
def respond(req_id, result):
    req = TutoringRequest.query.get_or_404(req_id)
    if req.tutor_id != current_user.id:
        abort(403)
    if req.status != "pending":
        flash(_("تم الرد على هذا الطلب مسبقاً."), "warning")
        return redirect(url_for("tutoring.my"))
    accept = result == "accept"
    respond_request(req, accept)
    audit("tutoring.respond", "tutoring_requests", req.id, amount=req.price_quote, currency="ILS", session_id=req.id)
    if accept:
        notify(req.student_id, "tutoring", _("قُبل طلب درسك الخصوصي"))
    else:
        notify(req.student_id, "tutoring", _("اعتذر المعلم عن طلبك"))
    flash(_("تم تحديث الطلب."), "success")
    return redirect(url_for("tutoring.my"))


@bp.route("/sessions/<int:session_id>", methods=["GET", "POST"])
@login_required
def session_detail(session_id):
    session_ = TutoringSession.query.get_or_404(session_id)
    if not can_access(current_user, session_):
        abort(403)
    form = SessionForm(obj=session_)
    pay_form = PaySessionForm(session_id=session_)
    is_tutor = session_.tutor_id == current_user.id
    if form.validate_on_submit():
        if not is_tutor:
            abort(403)
        update_session(
            session_,
            scheduled_at=form.scheduled_at.data,
            duration_min=form.duration_min.data,
            price=form.price.data,
            mode=form.mode.data,
            online_link=form.online_link.data,
            location=form.location.data,
        )
        flash(_("تم تحديث الجلسة."), "success")
        return redirect(url_for("tutoring.session_detail", session_id=session_.id))
    return render_template("tutoring/session.html", session_=session_, form=form, pay_form=pay_form, is_tutor=is_tutor)


@bp.post("/sessions/<int:session_id>/pay")
@login_required
def session_pay(session_id):
    session_ = TutoringSession.query.get_or_404(session_id)
    if not can_access(current_user, session_):
        abort(403)
    update_session(session_, payment_status="approved")
    audit(
        "tutoring.payment",
        "tutoring_sessions",
        session_.id,
        amount=session_.price,
        currency=session_.currency,
        gateway="manual",
        session_id=session_.id,
    )
    notify(session_.student_id, "tutoring", _("تم تأكيد دفع درسك الخصوصي"))
    flash(_("تم تأكيد استلام الدفع (يدوي)."), "success")
    return redirect(url_for("tutoring.session_detail", session_id=session_.id))


@bp.route("/sessions/<int:session_id>/status/<value>")
@login_required
def session_status(session_id, value):
    session_ = TutoringSession.query.get_or_404(session_id)
    if not can_access(current_user, session_):
        abort(403)
    if value not in ("completed", "cancelled"):
        abort(404)
    update_session(session_, status=value)
    audit("tutoring.session_status", "tutoring_sessions", session_.id, {"status": value})
    flash(_("تم تحديث حالة الجلسة."), "success")
    return redirect(url_for("tutoring.session_detail", session_id=session_.id))


@bp.route("/sessions/<int:session_id>/live-url")
@login_required
def live_session_url(session_id):
    """يعود URL الجلسة المباشرة للمعلم أو الطالب."""
    session_ = TutoringSession.query.get_or_404(session_id)
    if not can_access(current_user, session_):
        abort(403)
    url = generate_live_session_url(session_id, current_user.id)
    if not url:
        abort(403)
    return {"url": url}, 200


@bp.route("/sessions/<int:session_id>/live-status")
@login_required
def live_session_status(session_id):
    """يعرض حالة الجلسة الحية ونشاطها."""
    session_ = TutoringSession.query.get_or_404(session_id)
    if not can_access(current_user, session_):
        abort(403)
    return {
        "status": session_.status,
        "online_link": session_.online_link,
        "scheduled_at": session_.scheduled_at.isoformat() if session_.scheduled_at else None,
        "is_live": session_.status == "active",
    }, 200


@bp.route("/sessions/<int:session_id>/start-live", methods=["POST"])
@login_required
def start_live_session(session_id):
    """يبدأ الجلسة المباشرة (يحدث من قبل المعلم أو الطالب)."""
    session_ = TutoringSession.query.get_or_404(session_id)
    if not can_access(current_user, session_):
        abort(403)
    # تحديث الحالة وتوليد رابط Jitsi تلقائياً
    update_session_live_status(session_, live_status="active", user_id=current_user.id)
    audit("tutoring.live_start", "tutoring_sessions", session_.id, {"user_id": current_user.id})
    flash(_("تم بدء الجلسة المباشرة."), "success")
    return redirect(url_for("tutoring.session_detail", session_id=session_.id))


@bp.route("/sessions/<int:session_id>/end-live", methods=["POST"])
@login_required
def end_live_session(session_id):
    """ينهي الجلسة المباشرة (يحدث من قبل المعلم أو الطالب)."""
    session_ = TutoringSession.query.get_or_404(session_id)
    if not can_access(current_user, session_):
        abort(403)
    update_session_live_status(session_, live_status="completed", online_link=None)
    audit("tutoring.live_end", "tutoring_sessions", session_.id, {"user_id": current_user.id})
    flash(_("تم ending الجلسة المباشرة."), "success")
    return redirect(url_for("tutoring.session_detail", session_id=session_.id))
