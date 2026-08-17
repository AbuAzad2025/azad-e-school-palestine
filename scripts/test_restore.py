#!/usr/bin/env python3
"""
سكريبت اختبار الاستعادة — يعمل دورياً للتحقق من صلاحية النسخ الاحتياطية
"""

import os
import sys
import subprocess
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "backups"))
TEST_DB_NAME = os.getenv("TEST_DB_NAME", "azad_e_school_test_restore")
DB_URL = os.getenv("DATABASE_URL")


def run_cmd(cmd, timeout=300):
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Timeout after {timeout}s"
    except Exception as e:
        return False, "", str(e)


def create_test_database():
    """إنشاء قاعدة بيانات اختبار مؤقتة"""
    test_db_url = DB_URL.replace("/azad_e_school", f"/{TEST_DB_NAME}")
    # إنشاء قاعدة البيانات
    cmd = f'psql "{DB_URL}" -c "DROP DATABASE IF EXISTS {TEST_DB_NAME}; CREATE DATABASE {TEST_DB_NAME};"'
    success, _, stderr = run_cmd(cmd)
    if not success:
        print(f"ERROR: Failed to create test database: {stderr}")
        return None
    return test_db_url


def test_restore(backup_file):
    """اختبار استعادة نسخة احتياطية"""
    print(f"[{datetime.utcnow().isoformat()}] Testing restore of {backup_file.name}")

    # إنشاء قاعدة بيانات اختبار
    test_db_url = create_test_database()
    if not test_db_url:
        return False

    try:
        # استعادة النسخة
        if backup_file.suffix == ".gz":
            cmd = f'gunzip -c "{backup_file}" | psql "{test_db_url}"'
        else:
            cmd = f'psql "{test_db_url}" -f "{backup_file}"'

        success, _, stderr = run_cmd(cmd, timeout=600)
        if not success:
            print(f"ERROR: Restore failed: {stderr}")
            return False

        # التحقق من البيانات
        from app import create_app
        test_app = create_app()
        test_app.config["SQLALCHEMY_DATABASE_URI"] = test_db_url

        with test_app.app_context():
            from app.extensions import db
            from app.models.user import User
            from app.models.school import School

            # التحقق من وجود جداول وبيانات
            user_count = User.query.count()
            school_count = School.query.count()

            print(f"  Users: {user_count}, Schools: {school_count}")

            if user_count == 0 and school_count == 0:
                print("WARNING: Restored database appears empty")
                return False

        print(f"[{datetime.utcnow().isoformat()}] Restore test PASSED")
        return True

    except Exception as e:
        print(f"ERROR: Restore test failed: {e}")
        return False
    finally:
        # تنظيف قاعدة البيانات الاختبارية
        try:
            cmd = f'psql "{DB_URL}" -c "DROP DATABASE IF EXISTS {TEST_DB_NAME};"'
            subprocess.run(cmd, shell=True, capture_output=True)
        except:
            pass


def main():
    print(f"[{datetime.utcnow().isoformat()}] ===== بدء اختبار استعادة النسخ الاحتياطية =====")

    # العثور على أحدث نسخة احتياطية
    backup_dir = Path(os.getenv("BACKUP_DIR", "backups"))
    backups = sorted(Path("backups").glob("backup_*.sql*"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not backups:
        print("ERROR: No backup files found")
        sys.exit(1)

    # اختبار أحدث 3 نسخ
    tested = 0
    passed = 0
    for backup_file in backups[:3]:
        if test_restore(backup_file):
            passed += 1
        tested += 1

    print(f"\n=== RESULTS ===")
    print(f"Tested: {tested}, Passed: {passed}, Failed: {tested - passed}")

    if passed == tested:
        print("✅ ALL RESTORE TESTS PASSED")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()