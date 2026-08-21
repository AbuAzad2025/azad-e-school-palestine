#!/usr/bin/env python3
import os
import sys
import subprocess
import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "backups"))
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("ERROR: DATABASE_URL not set", file=sys.stderr)
    sys.exit(1)

BACKUP_ENABLED = os.getenv("BACKUP_ENABLED", "0") == "1"
S3_ENDPOINT = os.getenv("BACKUP_S3_ENDPOINT", "")
S3_BUCKET = os.getenv("BACKUP_S3_BUCKET", "")
S3_ACCESS_KEY = os.getenv("BACKUP_S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("BACKUP_S3_SECRET_KEY", "")
LOCAL_RETENTION_DAYS = int(os.getenv("BACKUP_LOCAL_RETENTION_DAYS", "7"))
WEEKLY_RETENTION = int(os.getenv("BACKUP_WEEKLY_RETENTION", "4"))
MONTHLY_RETENTION = int(os.getenv("BACKUP_MONTHLY_RETENTION", "12"))

# Encryption settings
BACKUP_ENCRYPT = os.getenv("BACKUP_ENCRYPT", "0") == "1"
BACKUP_ENCRYPT_METHOD = os.getenv("BACKUP_ENCRYPT_METHOD", "age")  # age|gpg
BACKUP_ENCRYPT_RECIPIENT = os.getenv("BACKUP_ENCRYPT_RECIPIENT", "")
BACKUP_ENCRYPT_PASSPHRASE = os.getenv("BACKUP_ENCRYPT_PASSPHRASE", "")


def encrypt_file(filepath: Path) -> Path:
    """Encrypt backup file using age or gpg."""
    if not BACKUP_ENCRYPT:
        return filepath

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from backup_encrypt import encrypt_age, encrypt_gpg
    except ImportError:
        print("WARNING: backup_encrypt module not found, skipping encryption", file=sys.stderr)
        return filepath

    if BACKUP_ENCRYPT_METHOD == "age":
        if BACKUP_ENCRYPT_PASSPHRASE:
            return encrypt_age(filepath, passphrase=BACKUP_ENCRYPT_PASSPHRASE)
        elif BACKUP_ENCRYPT_RECIPIENT:
            return encrypt_age(filepath, recipient=BACKUP_ENCRYPT_RECIPIENT)
        else:
            print("WARNING: No recipient or passphrase for age encryption", file=sys.stderr)
            return filepath
    else:
        if BACKUP_ENCRYPT_PASSPHRASE:
            return encrypt_gpg(filepath, passphrase=BACKUP_ENCRYPT_PASSPHRASE)
        elif BACKUP_ENCRYPT_RECIPIENT:
            return encrypt_gpg(filepath, recipient=BACKUP_ENCRYPT_RECIPIENT)
        else:
            print("WARNING: No recipient or passphrase for GPG encryption", file=sys.stderr)
            return filepath


def run_cmd(cmd, timeout=300):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Timeout after {timeout}s"
    except Exception as e:
        return False, "", str(e)


def create_db_backup():
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{timestamp}.sql.gz"
    filepath = BACKUP_DIR / filename
    print(f"[{datetime.utcnow().isoformat()}] Starting DB backup: {filename}")

    raw_path = BACKUP_DIR / f"backup_{timestamp}.sql"
    cmd = f'pg_dump "{DB_URL}" --no-owner --no-acl --clean --if-exists -f "{raw_path}"'
    success, _, stderr = run_cmd(cmd)
    if not success:
        print(f"ERROR: pg_dump failed: {stderr}", file=sys.stderr)
        return None

    try:
        with open(raw_path, "rb") as f_in:
            with gzip.open(filepath, "wb", compresslevel=6) as f_out:
                shutil.copyfileobj(f_in, f_out)
        raw_path.unlink()
    except Exception as e:
        print(f"WARNING: compression failed: {e}", file=sys.stderr)
        filepath = raw_path

    if filepath.stat().st_size == 0:
        print("ERROR: backup file is empty", file=sys.stderr)
        return None

    # Encrypt if enabled
    filepath = encrypt_file(filepath)

    size_mb = filepath.stat().st_size / (1024 * 1024)
    print(f"[{datetime.utcnow().isoformat()}] DB backup complete: {filepath.name} ({size_mb:.1f} MB)")
    return filepath


def create_uploads_backup():
    uploads_dir = Path("instance/uploads")
    if not uploads_dir.exists():
        print("No uploads directory found, skipping")
        return None
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filepath = BACKUP_DIR / f"uploads_{timestamp}.tar.gz"
    print(f"[{datetime.utcnow().isoformat()}] Starting uploads backup")
    cmd = f'tar -czf "{filepath}" -C instance uploads'
    success, _, stderr = run_cmd(cmd)
    if not success:
        print(f"WARNING: uploads backup failed: {stderr}", file=sys.stderr)
        return None

    # Encrypt if enabled
    filepath = encrypt_file(filepath)

    size_mb = filepath.stat().st_size / (1024 * 1024)
    print(f"[{datetime.utcnow().isoformat()}] Uploads backup: {filepath.name} ({size_mb:.1f} MB)")
    return filepath


def upload_to_s3(filepath):
    if not all([S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY]):
        print("S3 not configured, skipping upload")
        return False
    try:
        import boto3
        from botocore.config import Config as BotoConfig

        s3 = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            config=BotoConfig(signature_version="s3v4"),
        )
        key = f"backups/{filepath.name}"
        s3.upload_file(str(filepath), S3_BUCKET, key)
        print(f"[{datetime.utcnow().isoformat()}] Uploaded to S3: {key}")
        return True
    except Exception as e:
        print(f"WARNING: S3 upload failed: {e}", file=sys.stderr)
        return False


def cleanup_retention():
    cutoff_daily = datetime.utcnow() - timedelta(days=LOCAL_RETENTION_DAYS)
    cutoff_weekly = datetime.utcnow() - timedelta(weeks=WEEKLY_RETENTION)
    cutoff_monthly = datetime.utcnow() - timedelta(days=MONTHLY_RETENTION * 30)

    all_backups = sorted(BACKUP_DIR.glob("backup_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    deleted = 0

    for b in all_backups:
        mtime = datetime.utcfromtimestamp(b.stat().st_mtime)
        name = b.name
        is_weekly = "_W" in name
        is_monthly = "_M" in name

        if is_monthly and mtime < cutoff_monthly:
            b.unlink()
            deleted += 1
        elif is_weekly and mtime < cutoff_weekly:
            b.unlink()
            deleted += 1
        elif not is_weekly and not is_monthly and mtime < cutoff_daily:
            b.unlink()
            deleted += 1

    if deleted:
        print(f"[{datetime.utcnow().isoformat()}] Cleaned up {deleted} old backups")


def verify_backup(filepath):
    try:
        # Handle encrypted files
        if filepath.suffix in (".age", ".gpg"):
            print("WARNING: Cannot verify encrypted backup directly", file=sys.stderr)
            return True  # Skip verification for encrypted
        opener = gzip.open if filepath.suffix == ".gz" else open
        with opener(filepath, "rt", encoding="utf-8", errors="ignore") as f:
            first_lines = [next(f) for _ in range(5)]
        content = "".join(first_lines)
        return any(kw in content for kw in ("CREATE", "INSERT", "COPY", "--"))
    except Exception:
        return False


def main():
    print(f"[{datetime.utcnow().isoformat()}] ===== Backup started =====")

    if not BACKUP_ENABLED:
        print("BACKUP_ENABLED is false, skipping")
        sys.exit(0)

    db_path = create_db_backup()
    if not db_path:
        sys.exit(1)

    if not verify_backup(db_path):
        print("ERROR: backup verification failed", file=sys.stderr)
        sys.exit(1)

    upload_to_s3(db_path)

    uploads_path = create_uploads_backup()
    if uploads_path:
        upload_to_s3(uploads_path)

    cleanup_retention()

    print(f"[{datetime.utcnow().isoformat()}] ===== Backup completed =====")


if __name__ == "__main__":
    main()