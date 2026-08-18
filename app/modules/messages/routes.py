"""مسارات الرسائل: صندوق وارد، إرسال، خيوط، تحديد مقروءة."""

from app.extensions import db
from app.models.message import Message
from app.models.user import User
from app.services.messages import (
    get_thread,
    inbox,
    mark_read,
    send_message,
    sent,
    unread_count,
)
from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required

from . import bp


@bp.get("/inbox")
@login_required
def inbox_view():
    messages = inbox(current_user.id)
    unread = unread_count(current_user.id)
    return render_template("messages/inbox.html", messages=messages, unread=unread)


@bp.get("/sent")
@login_required
def sent_view():
    messages = sent(current_user.id)
    return render_template("messages/inbox.html", messages=messages, unread=unread_count(current_user.id), is_sent=True)


@bp.route("/send", methods=["GET", "POST"])
@bp.route("/send/<int:reply_to>", methods=["GET", "POST"])
@login_required
def compose(reply_to: int | None = None):
    parent = None
    if reply_to:
        parent = get_thread(reply_to)
        if not parent:
            abort(404)
    users = User.query.filter(User.id != current_user.id, User.is_active == True).order_by(User.name_ar).all()  # noqa: E712
    if request.method == "POST":
        recipient_id = request.form.get("recipient_id", type=int)
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()
        if not recipient_id or not subject or not body:
            flash(_("جميع الحقول مطلوبة."), "danger")
            return redirect(url_for("messages.compose", reply_to=reply_to))
        msg, error = send_message(
            sender_id=current_user.id,
            recipient_id=recipient_id,
            subject=subject,
            body=body,
            parent_message_id=parent.id if parent else None,
        )
        if error:
            flash(_(error), "danger")
            return redirect(url_for("messages.compose", reply_to=reply_to))
        flash(_("أُرسلت الرسالة."), "success")
        return redirect(url_for("messages.thread_view", message_id=msg.id))  # type: ignore[union-attr]
    return render_template("messages/compose.html", users=users, parent=parent)


@bp.get("/thread/<int:message_id>")
@login_required
def thread_view(message_id: int):
    msg = get_thread(message_id)
    if not msg:
        abort(404)
    if msg.recipient_id != current_user.id and msg.sender_id != current_user.id:
        abort(403)
    if msg.recipient_id == current_user.id:
        mark_read(msg.id, current_user.id)
    replies = (
        db.session.execute(db.select(Message).filter_by(parent_message_id=msg.id).order_by(Message.created_at.asc()))
        .scalars()
        .all()
    )
    return render_template("messages/thread.html", message=msg, replies=replies)


@bp.post("/mark-read/<int:message_id>")
@login_required
def mark_read_view(message_id: int):
    mark_read(message_id, current_user.id)
    return jsonify({"ok": True})


@bp.get("/unread-count")
@login_required
def unread_count_api():
    return jsonify({"count": unread_count(current_user.id)})
