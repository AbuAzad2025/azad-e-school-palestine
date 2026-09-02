"""خدمات المحتوى: الوحدات والدروس والمرفقات (رفع آمن عبر core/uploads)."""

import bleach
from sqlalchemy.orm import selectinload

from app.core.db import tx
from app.core.i18n import _
from app.core.uploads import save_upload
from app.extensions import db
from app.models.content import Lesson, LessonAttachment, Unit

# قائمة بيضاء لعناصر HTML المسموحة في دروس المعلم
ALLOWED_HTML_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "br",
    "hr",
    "strong",
    "em",
    "u",
    "s",
    "sub",
    "sup",
    "ul",
    "ol",
    "li",
    "a",
    "img",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "blockquote",
    "pre",
    "code",
    "div",
    "span",
}
ALLOWED_HTML_ATTRS = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "*": ["class", "style", "dir", "lang"],
}


def _sanitize_html(raw: str | None) -> str | None:
    """ينظف HTML من عناصر خطرة (script, iframe, event handlers) مع الحفاظ على التنسيق."""
    if not raw:
        return raw
    return bleach.clean(
        raw,
        tags=ALLOWED_HTML_TAGS,
        attributes=ALLOWED_HTML_ATTRS,
        strip=True,
    )


def create_unit(class_id: int, title: str, sort_order: int | None = None) -> Unit:
    def _create():
        u = Unit(class_id=class_id, title=title.strip(), sort_order=sort_order)
        db.session.add(u)
        return u

    return tx(_create)


def list_units(class_id: int):
    return Unit.query.filter_by(class_id=class_id).order_by(Unit.sort_order.asc(), Unit.id.asc()).all()


def list_lessons(class_id: int, include_drafts: bool = True):
    query = Lesson.query.filter_by(class_id=class_id)
    if not include_drafts:
        query = query.filter_by(status="published")
    return query.order_by(Lesson.sort_order.asc(), Lesson.id.asc()).all()


def get_lesson(lesson_id: int) -> Lesson | None:
    return Lesson.query.filter_by(id=lesson_id, deleted_at=None).options(selectinload(Lesson.attachments)).first()


def create_lesson(
    class_id: int,
    title: str,
    unit_id: int | None = None,
    body_html: str | None = None,
    created_by: int | None = None,
) -> tuple[Lesson | None, str | None]:
    title = (title or "").strip()
    if not title:
        return None, _("عنوان الدرس مطلوب.")

    def _create():
        lesson = Lesson(
            class_id=class_id,
            unit_id=unit_id,
            title=title,
            body_html=_sanitize_html(body_html),
            created_by=created_by,
        )
        db.session.add(lesson)
        return lesson

    return tx(_create), None


def update_lesson(lesson: Lesson, *, title: str, unit_id: int | None, body_html: str | None) -> None:
    def _update():
        lesson.title = title.strip()
        lesson.unit_id = unit_id
        lesson.body_html = _sanitize_html(body_html)
        lesson.version = (lesson.version or 1) + 1

    tx(_update)


def publish_lesson(lesson: Lesson) -> None:
    def _publish():
        lesson.status = "published"
        lesson.published_at = db.func.now()

    tx(_publish)


def unpublish_lesson(lesson: Lesson) -> None:
    def _unpublish():
        lesson.status = "draft"

    tx(_unpublish)


def add_attachment(lesson: Lesson, file, title: str | None = None) -> LessonAttachment:
    """يرفع المرفق (D7) ويُسجّله. يرفع TxError عند رفض الملف."""
    stored = save_upload(file)
    ext = stored.rsplit(".", 1)[-1].lower()
    kind = (
        "video"
        if ext in ("mp4", "webm")
        else ("audio" if ext in ("mp3",) else ("image" if ext in ("png", "jpg", "jpeg", "webp", "gif") else "file"))
    )

    def _add():
        att = LessonAttachment(
            lesson_id=lesson.id,
            kind=kind,
            title=title,
            stored_name=stored,
            original_name=file.filename,
            mime=file.mimetype,
            size_bytes=file.content_length or 0,
        )
        db.session.add(att)
        return att

    return tx(_add)


def add_youtube(lesson: Lesson, url: str, title: str | None = None) -> LessonAttachment:
    """مقطع فيديو خارجي (YouTube) — لا رفع ملف."""

    def _add():
        att = LessonAttachment(
            lesson_id=lesson.id,
            kind="video",
            title=title,
            stored_name=url.strip(),
            youtube_url=url.strip(),
        )
        db.session.add(att)
        return att

    return tx(_add)


def delete_attachment(attachment: LessonAttachment) -> None:
    def _delete():
        db.session.delete(attachment)

    tx(_delete)


def import_lesson(lesson_id: int, target_class_id: int, user_id: int) -> tuple[Lesson | None, str | None]:
    """استيراد درس مشترك إلى صف جديد — نسخ عميق مع المرفقات."""
    from app.models.class_room import ClassRoom

    lesson = get_lesson(lesson_id)
    if not lesson:
        return None, _("الدرس غير موجود.")
    if not lesson.is_shared:
        return None, _("هذا الدرس خاص ولا يمكن استيراده.")
    target_class = ClassRoom.query.filter_by(id=target_class_id, deleted_at=None).first()
    if not target_class:
        return None, _("الصف الهدف غير موجود.")

    def _import():
        new_lesson = Lesson(
            class_id=target_class_id,
            unit_id=None,
            title=lesson.title,
            body_html=lesson.body_html,
            sort_order=lesson.sort_order,
            status="draft",
            version=1,
            created_by=user_id,
            is_shared=False,
            original_lesson_id=lesson.id,
        )
        db.session.add(new_lesson)
        db.session.flush()

        for att in lesson.attachments:
            new_att = LessonAttachment(
                lesson_id=new_lesson.id,
                kind=att.kind,
                title=att.title,
                stored_name=att.stored_name,
                original_name=att.original_name,
                mime=att.mime,
                size_bytes=att.size_bytes,
                youtube_url=att.youtube_url,
                position=att.position,
            )
            db.session.add(new_att)

        return new_lesson

    return tx(_import), None


def shared_lessons(school_id: int, subject_id: int | None = None) -> list[Lesson]:
    """جلب الدروس المشتركة في المدرسة."""
    from sqlalchemy.orm import joinedload

    from app.models.class_room import ClassRoom

    query = (
        Lesson.query.join(ClassRoom, Lesson.class_id == ClassRoom.id)
        .options(joinedload(Lesson.class_room))
        .filter(
            ClassRoom.school_id == school_id,
            Lesson.is_shared.is_(True),
            Lesson.deleted_at.is_(None),
        )
    )
    if subject_id is not None:
        query = query.filter(ClassRoom.subject_id == subject_id)
    return query.order_by(Lesson.created_at.desc()).all()
