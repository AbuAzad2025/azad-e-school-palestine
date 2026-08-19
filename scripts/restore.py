#!/usr/bin/env python3
import os
import sys
import gzip
import subprocess
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_URL = os.getenv("DATABASE_URL")
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "backups"))


def run_cmd(cmd, timeout=600):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Timeout after {timeout}s"
    except Exception as e:
        return False, "", str(e)


def verify_integrity(filepath):
    try:
        opener = gzip.open if filepath.suffix == ".gz" else open
        with opener(filepath, "rt", encoding="utf-8", errors="ignore") as f:
            content = f.read(4096)
        return any(kw in content for kw in ("CREATE", "INSERT", "COPY"))
    except Exception:
        return False


def restore_db(filepath):
    print(f"Restoring database from {filepath.name}...")
    if filepath.suffix == ".gz":
        cmd = f'gunzip -c "{filepath}" | psql "{DB_URL}"'
    else:
        cmd = f'psql "{DB_URL}" -f "{filepath}"'
    success, _, stderr = run_cmd(cmd, timeout=600)
    if not success:
        print(f"ERROR: restore failed: {stderr}", file=sys.stderr)
        return False
    print("Database restored successfully")
    return True


def restore_uploads(filepath):
    uploads_dir = Path("instance/uploads")
    if uploads_dir.exists():
        backup_path = uploads_dir.with_name(f"uploads_before_restore_{Path(filepath).stem}")
        shutil.move(str(uploads_dir), str(backup_path))
        print(f"Backed up current uploads to {backup_path.name}")
    print(f"Restoring uploads from {filepath.name}...")
    cmd = f'tar -xzf "{filepath}" -C instance'
    success, _, stderr = run_cmd(cmd)
    if not success:
        print(f"ERROR: uploads restore failed: {stderr}", file=sys.stderr)
        return False
    print("Uploads restored successfully")
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: restore.py <backup_file> [--confirm]")
        print("Available backups:")
        for f in sorted(BACKUP_DIR.glob("backup_*.sql*")):
            print(f"  {f.name}")
        for f in sorted(BACKUP_DIR.glob("uploads_*.tar.gz")):
            print(f"  {f.name}")
        sys.exit(1)

    filepath = Path(sys.argv[1])
    if not filepath.exists():
        filepath = BACKUP_DIR / sys.argv[1]
    if not filepath.exists():
        print(f"ERROR: File not found: {sys.argv[1]}", file=sys.stderr)
        sys.exit(1)

    if "--confirm" not in sys.argv:
        print("WARNING: This will OVERWRITE the current database and uploads!")
        print(f"Backup file: {filepath.name} ({filepath.stat().st_size / 1024 / 1024:.1f} MB)")
        answer = input("Type 'YES' to confirm: ")
        if answer != "YES":
            print("Aborted.")
            sys.exit(0)

    if filepath.suffix in (".gz", ".sql"):
        if not verify_integrity(filepath):
            print("ERROR: Backup file integrity check failed", file=sys.stderr)
            sys.exit(1)
        restore_db(filepath)

    uploads_file = BACKUP_DIR / f"uploads_{filepath.stem.replace('backup_', '')}.tar.gz"
    if uploads_file.exists():
        restore_uploads(uploads_file)

    print("Restore completed successfully!")


if __name__ == "__main__":
    main()
