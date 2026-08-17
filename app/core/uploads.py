"""الرفع الآمن للملفات (D7) — نقطة مركزية واحدة لكل المرفوعات.

القواعد: قائمة بيضاء بالامتدادات، حجم محدود، اسم عشوائي (لا اعتماد على اسم المستخدم)،
والتخزين خارج المجلد العام دائماً. تُعاد أسماء التخزين فقط للجداول.

AMENDED: فحص magic bytes للتحقق من نوع الملف الفعلي بدلاً من الاعتماد على MIME header.
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

# Magic bytes → (mime_type, description) — للتحقق من محتوى الملف الفعلي
MAGIC_SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"RIFF", "video/webm"),  # webm/matroska
    (b"\x00\x00\x00", None),  # mp4 — requires deeper check below
    (b"%PDF", "application/pdf"),
    (b"PK\x03\x04", None),  # ZIP (docx/xlsx/pptx) — extension determines type
    (b"ID3", "audio/mpeg"),
    (b"\xff\xfb", "audio/mpeg"),
    (b"\xff\xf3", "audio/mpeg"),
]

# الامتدادات المدعومة لملفات Office (ZIP-based)
OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx"}


def _detect_magic_type(header: bytes, ext: str) -> str | None:
    """يُعيد نوع MIME الفعلي من magic bytes أو None إذا لم يتعرف."""
    if len(header) < 4:
        return None

    # PNG
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    # JPEG
    if header[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    # PDF
    if header[:4] == b"%PDF":
        return "application/pdf"
    # MP4 (ftyp box)
    if header[4:8] == b"ftyp":
        return "video/mp4"
    # WebM/Matroska
    if header[:4] == b"RIFF":
        return "video/webm"
    # ZIP (docx/xlsx/pptx)
    if header[:4] == b"PK\x03\x04":
        ext_lower = ext.lower()
        if ext_lower in OFFICE_EXTENSIONS:
            mime_map = {
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            }
            return mime_map.get(ext_lower)
        return None
    # MP3
    if header[:3] == b"ID3" or header[:2] in (b"\xff\xfb", b"\xff\xf3"):
        return "audio/mpeg"
    # GIF
    if header[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    # WebP (RIFF....WEBP)
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"

    return None


def allowed_extension(filename: str) -> bool:
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext in current_app.config.get("ALLOWED_EXTENSIONS", set())


def allowed_mime(mimetype: str) -> bool:
    """يتحقق من نوع MIME ضد القائمة البيضاء."""
    return mimetype in ALLOWED_MIME_TYPES


def validate_file_content(file: FileStorage, ext: str) -> bool:
    """يتحقق من محتوى الملف الفعلي عبر magic bytes (يمنع رفع shell/ executables)."""
    header = file.read(16)
    file.seek(0)  # إعادة المؤشر للبداية

    detected = _detect_magic_type(header, ext)
    if detected is None:
        # لا نستطيع التعرف — نرفض للأمان
        return False

    return detected in ALLOWED_MIME_TYPES


def save_upload(file: FileStorage, subfolder: str = "") -> str:
    """يحفظ الملف خارج public ويعي stored_name العشوائي. يرفع TxError عند الرفض."""
    if not file or not file.filename:
        raise TxError("لا يوجد ملف.")
    if not allowed_extension(file.filename):
        raise TxError("امتداد الملف غير مسموح.")
    if not allowed_mime(file.mimetype):
        raise TxError("نوع الملف غير مسموح (MIME type).")

    # فحص المحتوى الفعلي (magic bytes)
    ext = Path(file.filename).suffix.lower()
    if not validate_file_content(file, ext):
        raise TxError("محتوى الملف لا يتطابق مع الامتداد المُصرَّح.")

    stored = f"{uuid.uuid4().hex}{ext}"
    base: Path = current_app.config["UPLOAD_FOLDER"]
    folder = base / subfolder if subfolder else base
    folder.mkdir(parents=True, exist_ok=True)
    file.save(folder / stored)
    return f"{subfolder}/{stored}" if subfolder else stored
