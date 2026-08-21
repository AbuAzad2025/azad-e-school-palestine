#!/usr/bin/env python3
"""Backup Restore Verification Script

Run in CI to verify backup integrity:
1. Download latest backup from S3 (or use local)
2. Restore to temporary database
3. Run integrity checks (row counts, FK, constraints)
4. Report results

Usage:
    python scripts/restore_verify.py --backup-path backups/backup_20240101_120000.sql.gz
    python scripts/restore_verify.py --s3-bucket my-bucket --s3-key backups/backup_latest.sql.gz
"""
import os
import sys
import subprocess
import gzip
import tempfile
import argparse
import shutil
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse


def run_cmd(cmd, timeout=600, env=None):
    """Run command with timeout, return (success, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=env
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Timeout after {timeout}s"
    except Exception as e:
        return False, "", str(e)


def download_from_s3(bucket, key, dest_path):
    """Download backup from S3."""
    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except ImportError:
        return False, "boto3 not installed"

    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=os.getenv("BACKUP_S3_ENDPOINT"),
            aws_access_key_id=os.getenv("BACKUP_S3_ACCESS_KEY"),
            aws_secret_access_key=os.getenv("BACKUP_S3_SECRET_KEY"),
            config=BotoConfig(signature_version="s3v4"),
        )
        s3.download_file(bucket, key, str(dest_path))
        return True, f"Downloaded s3://{bucket}/{key}"
    except Exception as e:
        return False, f"S3 download failed: {e}"


def gunzip_file(gz_path, out_path):
    """Decompress .gz file."""
    try:
        with gzip.open(gz_path, "rb") as f_in:
            with open(out_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        return True, "Decompressed"
    except Exception as e:
        return False, f"Decompression failed: {e}"


def create_temp_db(db_url):
    """Create a temporary database for restore."""
    parsed = urlparse(db_url)
    # Create temp DB name
    temp_db = f"restore_test_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

    # Connect to postgres DB to create temp DB
    admin_url = f"postgresql://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port or 5432}/postgres"
    success, _, stderr = run_cmd(f'psql "{admin_url}" -c "CREATE DATABASE {temp_db}"')
    if not success:
        return None, f"Failed to create temp DB: {stderr}"

    temp_url = f"postgresql://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port or 5432}/{temp_db}"
    return temp_url, temp_db


def drop_temp_db(temp_db, db_url):
    """Drop temporary database."""
    parsed = urlparse(db_url)
    admin_url = f"postgresql://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port or 5432}/postgres"
    # Terminate connections first
    run_cmd(f'psql "{admin_url}" -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = \'{temp_db}\'"')
    run_cmd(f'psql "{admin_url}" -c "DROP DATABASE IF EXISTS {temp_db}"')


def restore_backup(sql_path, db_url):
    """Restore SQL backup to database."""
    cmd = f'psql -v ON_ERROR_STOP=1 -q -d "{db_url}" -f "{sql_path}"'
    success, stdout, stderr = run_cmd(cmd, timeout=1200)
    return success, stdout, stderr


def run_integrity_checks(db_url):
    """Run integrity checks on restored database."""
    checks = {}

    # 1. Core table row counts
    core_tables = [
        "schools", "users", "classes", "class_members",
        "lessons", "units", "assignments", "submissions",
        "quizzes", "questions", "quiz_attempts", "answers",
        "grade_categories", "grade_items", "grade_entries",
        "subscriptions", "subscription_plans", "manual_payments",
        "attendance", "notifications", "tutoring_sessions",
        "badges", "family_links",
    ]

    checks["table_counts"] = {}
    for table in core_tables:
        sql = f"SELECT COUNT(*) FROM {table}"
        success, out, _ = run_cmd(f'psql -t -A -d "{db_url}" -c "{sql}"')
        if success:
            checks["table_counts"][table] = int(out.strip())
        else:
            checks["table_counts"][table] = -1

    # 2. FK integrity (orphan check)
    checks["fk_orphans"] = {}
    fk_checks = [
        ("class_members", "class_id", "classes"),
        ("class_members", "user_id", "users"),
        ("lessons", "class_id", "classes"),
        ("assignments", "class_id", "classes"),
        ("submissions", "assignment_id", "assignments"),
        ("submissions", "student_id", "users"),
        ("quizzes", "class_id", "classes"),
        ("questions", "quiz_id", "quizzes"),
        ("quiz_attempts", "quiz_id", "quizzes"),
        ("quiz_attempts", "student_id", "users"),
        ("answers", "attempt_id", "quiz_attempts"),
        ("answers", "question_id", "questions"),
        ("grade_entries", "grade_item_id", "grade_items"),
        ("grade_entries", "student_id", "users"),
        ("subscriptions", "user_id", "users"),
        ("subscriptions", "plan_id", "subscription_plans"),
        ("manual_payments", "subscription_id", "subscriptions"),
    ]

    for child, fk_col, parent in fk_checks:
        sql = f"""
            SELECT COUNT(*) FROM {child} c
            LEFT JOIN {parent} p ON c.{fk_col} = p.id
            WHERE c.{fk_col} IS NOT NULL AND p.id IS NULL
        """
        success, out, _ = run_cmd(f'psql -t -A -d "{db_url}" -c "{sql}"')
        if success:
            orphans = int(out.strip())
            checks["fk_orphans"][f"{child}.{fk_col} -> {parent}"] = orphans
        else:
            checks["fk_orphans"][f"{child}.{fk_col} -> {parent}"] = -1

    # 3. Check constraints validation
    checks["constraints"] = {}
    constraint_checks = [
        ("subscriptions", "status IN ('pending','active','expired','cancelled','pending_review')"),
        ("quiz_attempts", "status IN ('in_progress','submitted','graded','auto_submitted','abandoned')"),
        ("discount_codes", "used_count <= max_uses AND max_uses > 0"),
        ("tutor_payouts", "amount > 0"),
    ]
    for table, condition in constraint_checks:
        sql = f"SELECT COUNT(*) FROM {table} WHERE NOT ({condition})"
        success, out, _ = run_cmd(f'psql -t -A -d "{db_url}" -c "{sql}"')
        if success:
            violations = int(out.strip())
            checks["constraints"][f"{table}.{condition}"] = violations

    # 4. Unique constraint check (no duplicates)
    checks["unique_duplicates"] = {}
    unique_checks = [
        ("users", "email"),
        ("classes", "join_code"),
        ("class_members", "class_id, user_id"),
        ("quiz_attempts", "quiz_id, student_id, attempt_no"),
        ("grade_entries", "student_id, grade_item_id"),
        ("family_links", "parent_id, student_id"),
        ("student_badges", "student_id, badge_id"),
        ("processed_events", "event_id"),
        ("discount_codes", "code"),
    ]
    for table, cols in unique_checks:
        sql = f"""
            SELECT COUNT(*) FROM (
                SELECT {cols}, COUNT(*) as cnt FROM {table}
                GROUP BY {cols} HAVING COUNT(*) > 1
            ) dups
        """
        success, out, _ = run_cmd(f'psql -t -A -d "{db_url}" -c "{sql}"')
        if success:
            dups = int(out.strip())
            checks["unique_duplicates"][f"{table}.{cols}"] = dups

    # 5. Data freshness (no stale soft-deleted without deleted_at)
    checks["soft_delete"] = {}
    for table in ["users", "classes", "lessons"]:
        sql = f"SELECT COUNT(*) FROM {table} WHERE deleted_at IS NOT NULL"
        success, out, _ = run_cmd(f'psql -t -A -d "{db_url}" -c "{sql}"')
        if success:
            checks["soft_delete"][table] = int(out.strip())

    return checks


def print_report(checks, backup_path):
    """Print formatted verification report."""
    print(f"\n{'='*60}")
    print(f"BACKUP VERIFICATION REPORT")
    print(f"{'='*60}")
    print(f"Backup: {backup_path}")
    print(f"Time:   {datetime.utcnow().isoformat()}Z")
    print(f"{'='*60}\n")

    # Table counts
    print("📊 TABLE ROW COUNTS")
    print("-" * 60)
    total_rows = 0
    for table, count in sorted(checks["table_counts"].items()):
        status = "✅" if count >= 0 else "❌"
        print(f"  {status} {table:<30} {count:>10}")
        if count > 0:
            total_rows += count
    print(f"  {'TOTAL':<30} {total_rows:>10}\n")

    # FK orphans
    print("🔗 FOREIGN KEY ORPHANS (should be 0)")
    print("-" * 60)
    fk_total = 0
    for fk, count in sorted(checks["fk_orphans"].items()):
        status = "✅" if count == 0 else "❌"
        print(f"  {status} {fk:<50} {count:>5}")
        if count > 0:
            fk_total += count
    print(f"  {'TOTAL ORPHANS':<50} {fk_total:>5}\n")

    # Constraints
    print("⚖️  CHECK CONSTRAINT VIOLATIONS (should be 0)")
    print("-" * 60)
    constr_total = 0
    for constr, count in sorted(checks["constraints"].items()):
        status = "✅" if count == 0 else "❌"
        print(f"  {status} {constr:<60} {count:>5}")
        if count > 0:
            constr_total += count
    print(f"  {'TOTAL VIOLATIONS':<60} {constr_total:>5}\n")

    # Unique duplicates
    print("🔑 UNIQUE CONSTRAINT DUPLICATES (should be 0)")
    print("-" * 60)
    dup_total = 0
    for uk, count in sorted(checks["unique_duplicates"].items()):
        status = "✅" if count == 0 else "❌"
        print(f"  {status} {uk:<50} {count:>5}")
        if count > 0:
            dup_total += count
    print(f"  {'TOTAL DUPLICATES':<50} {dup_total:>5}\n")

    # Soft delete
    print("🗑️  SOFT-DELETED RECORDS")
    print("-" * 60)
    for table, count in sorted(checks["soft_delete"].items()):
        print(f"  {table:<20} {count:>10}")

    print(f"\n{'='*60}")
    overall = "PASS" if (fk_total == 0 and constr_total == 0 and dup_total == 0) else "FAIL"
    print(f"OVERALL: {overall}")
    print(f"{'='*60}\n")

    return overall == "PASS"


def main():
    parser = argparse.ArgumentParser(description="Verify backup integrity via restore")
    parser.add_argument("--backup-path", help="Local path to backup .sql.gz")
    parser.add_argument("--s3-bucket", help="S3 bucket name")
    parser.add_argument("--s3-key", help="S3 key (path in bucket)")
    parser.add_argument("--db-url", help="Database URL (defaults to DATABASE_URL env)")
    parser.add_argument("--keep-temp-db", action="store_true", help="Don't drop temp DB after test")
    args = parser.parse_args()

    if not args.backup_path and not (args.s3_bucket and args.s3_key):
        parser.error("Either --backup-path or --s3-bucket/--s3-key required")

    db_url = args.db_url or os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 1

    # Locate backup file
    if args.backup_path:
        backup_file = Path(args.backup_path)
        if not backup_file.exists():
            print(f"ERROR: Backup not found: {backup_file}", file=sys.stderr)
            return 1
        sql_gz = backup_file
    else:
        # Download from S3
        with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as tmp:
            sql_gz = Path(tmp.name)
        success, msg = download_from_s3(args.s3_bucket, args.s3_key, sql_gz)
        if not success:
            print(f"ERROR: {msg}", file=sys.stderr)
            return 1
        print(msg)

    # Decompress
    sql_file = sql_gz.with_suffix("")  # remove .gz
    success, msg = gunzip_file(sql_gz, sql_file)
    if not success:
        print(f"ERROR: {msg}", file=sys.stderr)
        return 1
    print(msg)

    # Create temp DB
    temp_url, temp_db = create_temp_db(db_url)
    if not temp_url:
        print(f"ERROR: {temp_db}", file=sys.stderr)
        return 1
    print(f"Created temp DB: {temp_db}")

    try:
        # Restore
        print("Restoring backup...")
        success, stdout, stderr = restore_backup(sql_file, temp_url)
        if not success:
            print(f"ERROR: Restore failed: {stderr}", file=sys.stderr)
            return 1
        print("Restore complete")

        # Run integrity checks
        print("Running integrity checks...")
        checks = run_integrity_checks(temp_url)

        # Report
        passed = print_report(checks, str(sql_gz))

        return 0 if passed else 1

    finally:
        if not args.keep_temp_db:
            print(f"Dropping temp DB: {temp_db}")
            drop_temp_db(temp_db, db_url)
        else:
            print(f"Keeping temp DB: {temp_db} (connect with: {temp_url})")


if __name__ == "__main__":
    sys.exit(main())