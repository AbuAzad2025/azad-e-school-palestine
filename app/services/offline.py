"""خدمات وضع عدم الاتصال — تنزيل المحتوى."""

from datetime import UTC, datetime, timedelta

from app.core.db import tx
from app.extensions import db
from app.models.offline import OfflineDownload


def mark_for_download(student_id: int, attachment_id: int, lesson_id: int) -> OfflineDownload | None:
    existing = OfflineDownload.query.filter_by(student_id=student_id, attachment_id=attachment_id).first()
    if existing:
        return None

    def _mark():
        obj = OfflineDownload(
            student_id=student_id,
            attachment_id=attachment_id,
            lesson_id=lesson_id,
            status="ready",
            downloaded_at=db.func.now(),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        db.session.add(obj)
        return obj

    return tx(_mark)


def mark_downloaded(download_id: int) -> None:
    def _mark():
        d = db.session.get(OfflineDownload, download_id)
        if d:
            d.status = "ready"
            d.downloaded_at = db.func.now()

    tx(_mark)


def get_offline_items(student_id: int):
    return OfflineDownload.query.filter_by(student_id=student_id).order_by(OfflineDownload.downloaded_at.desc()).all()


def remove_offline(download_id: int) -> None:
    def _remove():
        d = db.session.get(OfflineDownload, download_id)
        if d:
            db.session.delete(d)

    tx(_remove)


def expire_old_downloads() -> int:
    def _expire():
        from sqlalchemy import update

        result = db.session.execute(
            update(OfflineDownload)
            .where(OfflineDownload.expires_at < datetime.now(UTC), OfflineDownload.status == "ready")
            .values(status="expired")
        )
        return result.rowcount  # type: ignore[attr-defined]

    return tx(_expire)
