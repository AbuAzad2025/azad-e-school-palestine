"""خدمات المحتوى: الوحدات والدروس والمرفقات (رفع آمن عبر core/uploads)."""

import bleach
from sqlalchemy.orm import selectinload

from app.core.db import tx
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
        return Unit(class_id=class_id, title=title.strip(), sort_order=sort_order)

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
        return None, "عنوان الدرس مطلوب."

    def _create():
        return Lesson(
            class_id=class_id,
            unit_id=unit_id,
            title=title,
            body_html=_sanitize_html(body_html),
            created_by=created_by,
        )

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
        return LessonAttachment(
            lesson_id=lesson.id,
            kind=kind,
            title=title,
            stored_name=stored,
            original_name=file.filename,
            mime=file.mimetype,
            size_bytes=file.content_length or 0,
        )

    return tx(_add)


def add_youtube(lesson: Lesson, url: str, title: str | None = None) -> LessonAttachment:
    """مقطع فيديو خارجي (YouTube) — لا رفع ملف."""

    def _add():
        return LessonAttachment(
            lesson_id=lesson.id,
            kind="video",
            title=title,
            youtube_url=url.strip(),
        )

    return tx(_add)


def delete_attachment(attachment: LessonAttachment) -> None:
    def _delete():
        db.session.delete(attachment)

    tx(_delete)
