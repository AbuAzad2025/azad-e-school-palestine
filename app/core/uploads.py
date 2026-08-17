"""الرفع الآمن للملفات (D7) — نقطة مركزية واحدة لكل المرفوعات.

القواعد: قائمة بيضاء بالامتدادات، حجم محدود، اسم عشوائي (لا اعتماد على اسم المستخدم)،
والتخزين خارج المجلد العام دائماً. تُعاد أسماء التخزين فقط للجداول.
"""

import uuid
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.core.db import TxError

# أنواع MIME المسموحة (قائمة بيضاء) — مُطابقة للامتدادات
ALLOWED_MIME_TYPES = {
    # صور
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    # مستندات
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # pptx
    # فيديو
    "video/mp4",
    "video/webm",
    # صوت
    "audio/mpeg",
    "audio/mp3",
    "audio/webm",
}


def allowed_extension(filename: str) -> bool:
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext in current_app.config.get("ALLOWED_EXTENSIONS", set())


def allowed_mime(mimetype: str) -> bool:
    """يتحقق من نوع MIME ضد القائمة البيضاء."""
    return mimetype in ALLOWED_MIME_TYPES


def save_upload(file: FileStorage, subfolder: str = "") -> str:
    """يحفظ الملف خارج public ويعيد stored_name العشوائي. يرفع TxError عند الرفض."""
    if not file or not file.filename:
        raise TxError("لا يوجد ملف.")
    if not allowed_extension(file.filename):
        raise TxError("امتداد الملف غير مسموح.")
    if not allowed_mime(file.mimetype):
        raise TxError("نوع الملف غير مسموح (MIME type).")

    ext = Path(file.filename).suffix.lower()
    stored = f"{uuid.uuid4().hex}{ext}"
    base: Path = current_app.config["UPLOAD_FOLDER"]
    folder = base / subfolder if subfolder else base
    folder.mkdir(parents=True, exist_ok=True)
    file.save(folder / stored)
    return f"{subfolder}/{stored}" if subfolder else stored
