#!/usr/bin/env python3
"""
سكريبت النسخ الاحتياطي الآلي — يعمل عبر cron
يدعم: pg_dump مضغوط، retention، إشعارات، تحقق من التكامل
"""

import os
import sys
import subprocess
import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# إضافة مسار المشروع
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db

# إعدادات من متغيرات البيئة
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "backups"))
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("ERROR: DATABASE_URL غير مضبوط", file=sys.stderr)
    sys.exit(1)

RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
MAX_BACKUPS = int(os.getenv("MAX_BACKUPS", "50"))
COMPRESS = os.getenv("BACKUP_COMPRESS", "1") == "1"
NOTIFY_WEBHOOK = os.getenv("BACKUP_NOTIFY_WEBHOOK", "")


def run_cmd(cmd, timeout=300):
    """تشغيل أمر والتحقق من النتيجة"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Timeout after {timeout}s"
    except Exception as e:
        return False, "", str(e)


def create_backup():
    """إنشاء نسخة احتياطية مضغوطة"""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{timestamp}.sql"
    filepath = BACKUP_DIR / filename

    print(f"[{datetime.utcnow().isoformat()}] بدء النسخ الاحتياطي: {filename}")

    # pg_dump مع خيارات محسنة
    cmd = f'pg_dump "{DB_URL}" --no-owner --no-acl --clean --if-exists -f "{filepath}"'
    success, stdout, stderr = run_cmd(cmd)

    if not success:
        print(f"ERROR: فشل النسخ الاحتياطي: {stderr}", file=sys.stderr)
        return False, None

    # ضغط الملف
    if COMPRESS:
        gz_path = filepath.with_suffix(".sql.gz")
        print(f"[{datetime.utcnow().isoformat()}] ضغط الملف...")
        try:
            with open(filepath, "rb") as f_in:
                with gzip.open(gz_path, "wb", compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            filepath.unlink()  # حذف الأصل
            filepath = gz_path
            filename = gz_path.name
            print(f"[{datetime.utcnow().isoformat()}] تم الضغط: {gz_path.name}")
        except Exception as e:
            print(f"WARNING: فشل الضغط: {e}", file=sys.stderr)

    # تحقق من التكامل
    size = filepath.stat().st_size
    if size == 0:
        print("ERROR: ملف النسخ الاحتياطي فارغ", file=sys.stderr)
        return False, None

    print(f"[{datetime.utcnow().isoformat()}] اكتمل النسخ الاحتياطي: {filename} ({filepath.stat().st_size / 1024 / 1024:.1f} MB)")
    return True, filepath


def cleanup_old_backups():
    """حذف النسخ القديمة حسب السياسة"""
    backups = sorted(BACKUP_DIR.glob("backup_*.sql*"), key=lambda p: p.stat().st_mtime, reverse=True)

    # حذف القديم حسب العمر
    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    deleted = 0
    for b in backups:
        mtime = datetime.fromtimestamp(b.stat().st_mtime)
        if mtime < cutoff:
            b.unlink()
            deleted += 1
            print(f"[{datetime.utcnow().isoformat()}] حُذف نسخة قديمة: {b.name}")

    # حذف الزائد عن الحد الأقصى
    backups = sorted(BACKUP_DIR.glob("backup_*.sql*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if len(backups) > MAX_BACKUPS:
        for b in backups[MAX_BACKUPS:]:
            b.unlink()
            deleted += 1
            print(f"[{datetime.utcnow().isoformat()}] حُذف نسخة زائدة: {b.name}")

    if deleted:
        print(f"[{datetime.utcnow().isoformat()}] تم حذف {deleted} نسخة احتياطية قديمة")


def verify_backup(filepath):
    """التحقق من صلاحية ملف النسخ الاحتياطي"""
    try:
        # محاولة قراءة أول أسطر الملف للتحقق من صلاحيته
        if filepath.suffix == ".gz":
            import gzip
            opener = gzip.open
        else:
            opener = open

        with opener(filepath, "rt", encoding="utf-8", errors="ignore") as f:
            first_lines = [next(f) for _ in range(5)]

        # التحقق من وجود أوامر SQL صحيحة
        content = "".join(first_lines)
        if "CREATE" in content or "INSERT" in content or "COPY" in content or "--" in content:
            return True

        print(f"WARNING: ملف النسخ الاحتياطي قد يكون تالفاً: {filepath.name}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"ERROR: فشل التحقق من {filepath.name}: {e}", file=sys.stderr)
        return False


def send_notification(message, status="info"):
    """إرسال إشعار عبر webhook إذا مُضبوط"""
    if not NOTIFY_WEBHOOK:
        return

    import requests
    try:
        payload = {
            "text": message,
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
        }
        requests.post(NOTIFY_WEBHOOK, json=payload, timeout=10)
    except Exception as e:
        print(f"WARNING: فشل إرسال الإشعار: {e}", file=sys.stderr)


def main():
    print(f"[{datetime.utcnow().isoformat()}] ===== بدء عملية النسخ الاحتياطي =====")

    # 1. إنشاء النسخة
    success, filepath = create_backup()
    if not success:
        send_notification("❌ فشل النسخ الاحتياطي", "error")
        sys.exit(1)

    # 2. التحقق من التكامل
    if not verify_backup(filepath):
        send_notification(f"⚠️ النسخة الاحتياطية قد تكون تالفة: {filepath.name}", "warning")
        sys.exit(1)

    # 3. تنظيف النسخ القديمة
    cleanup_old_backups()

    # 3. إشعار النجاح
    size_mb = filepath.stat().st_size / 1024 / 1024
    send_notification(f"✅ تم النسخ الاحتياطي بنجاح: {filepath.name} ({size_mb:.1f} MB)", "success")

    print(f"[{datetime.utcnow().isoformat()}] ===== اكتملت العملية بنجاح =====")


if __name__ == "__main__":
    main()