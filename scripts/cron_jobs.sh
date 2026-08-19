#!/bin/bash
# Cron Jobs for Azad E-School Platform
# Add to crontab: crontab -e

# Environment
export PATH=/usr/local/bin:/usr/bin:/bin
export PYTHONPATH=/path/to/14-e-school-palestine
export DATABASE_URL=postgresql+psycopg2://postgres:password@localhost:5432/azad_e_school
export BACKUP_DIR=/path/to/backups
export BACKUP_RETENTION_DAYS=30
export MAX_BACKUPS=50
export BACKUP_COMPRESS=1
export BACKUP_NOTIFY_WEBHOOK=https://your-webhook-url
export TEST_DB_NAME=azad_e_school_test_restore
export DATABASE_URL=postgresql+psycopg2://postgres:password@localhost:5432/azad_e_school

# ============================================================
# BACKUP JOBS
# ============================================================

# Daily backup at 2:30 AM
30 2 * * * /path/to/venv/bin/python /path/to/scripts/backup.py >> /var/log/azad_backup.log 2>&1

# Hourly backup (optional, for critical data)
# 0 * * * * /path/to/venv/bin/python /path/to/scripts/backup.py >> /var/log/azad_backup_hourly.log 2>&1

# Weekly restore test - Sunday 3:00 AM
0 3 * * 0 /path/to/venv/bin/python /path/to/scripts/test_restore.py >> /var/log/azad_restore_test.log 2>&1

# Monthly cleanup - 1st of month 4:00 AM
0 4 1 * * /path/to/venv/bin/python -c "
import os, shutil
from pathlib import Path
backup_dir = Path('/path/to/backups')
for f in Path('backups').glob('backup_*.sql*'):
    if f.stat().st_mtime < (time.time() - 90*86400):
        f.unlink()
        print(f'Deleted old backup: {f.name}')
" >> /var/log/azad_cleanup.log 2>&1

# ============================================================
# PAYMENT JOBS
# ============================================================

# Daily payment reminders - 7:00 AM
0 7 * * * /path/to/venv/bin/python /path/to/scripts/daily_reminders.py >> /var/log/azad_reminders.log 2>&1

# Process pending payments every 5 minutes
*/5 * * * * /path/to/venv/bin/python -c "
import os, sys
sys.path.insert(0, '/path/to/14-e-school-palestine')
os.environ['PYTHONPATH'] = '/path/to/14-e-school-palestine'
from app import create_app
from app.extensions import db
from app.models.billing import ManualPayment
from app.services.billing import approve_payment
app = create_app()
with app.app_context():
    for p in ManualPayment.query.filter_by(status='pending').all():
        # Check if payment expired (older than 24h)
        if p.created_at < datetime.utcnow() - timedelta(hours=24):
            p.status = 'expired'
            db.session.commit()
" >> /var/log/azad_payment_cleanup.log 2>&1

# Check Stripe webhooks every minute (if using Stripe)
# * * * * * curl -X POST https://yourdomain.com/api/ai/chat/stream -H "Content-Type: application/json" -d '{}' >> /dev/null 2>&1

# ============================================================
# AI USAGE MONITORING
# ============================================================

# Daily AI usage report - 6:00 AM
0 6 * * * /path/to/venv/bin/python -c "
import os, sys, json
sys.path.insert(0, '/path/to/14-e-school-palestine')
os.environ['PYTHONPATH'] = '/path/to/14-e-school-palestine'
from app import create_app
from app.services.ai import get_ai_service
app = create_app()
with app.app_context():
    from app.services.ai import get_ai_service
    svc = get_ai_service()
    stats = svc.get_usage_stats(days=1)
    print(json.dumps(stats, indent=2, default=str))
" >> /var/log/azad_ai_daily.log 2>&1

# Weekly AI budget alert - Monday 9:00 AM
0 9 * * 1 /path/to/venv/bin/python -c "
import os, sys
sys.path.insert(0, '/path/to/14-e-school-palestine')
os.environ['PYTHONPATH'] = '/path/to/14-e-school-palestine'
from app import create_app
from app.services.ai import get_ai_service
app = create_app()
with app.app_context():
    from app.services.ai import get_ai_service
    svc = get_ai_service()
    budget = svc._budget_tracker.get_usage() if svc._budget_tracker else {}
    if budget.get('usage_percent', 0) > 80:
        print(f'WARNING: AI Budget at {budget.get(\"usage_percent\", 0)}%')
" >> /var/log/azad_ai_budget.log 2>&1

# ============================================================
# BACKUP HEALTH CHECK
# ============================================================

# Daily backup health check - 5:00 AM
0 5 * * * /path/to/venv/bin/python -c "
import os, sys
sys.path.insert(0, '/path/to/14-e-school-palestine')
os.environ['PYTHONPATH'] = '/path/to/14-e-school-palestine'
from pathlib import Path
from datetime import datetime, timedelta
backup_dir = Path('/path/to/backups')
backups = list(Path('backups').glob('backup_*.sql*'))
if not backups:
    print('ERROR: No backups found!')
    sys.exit(1)
latest = max(backups, key=lambda p: p.stat().st_mtime)
age = datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)
if age > timedelta(hours=25):
    print(f'WARNING: Latest backup is {age} old!')
    sys.exit(1)
size_mb = latest.stat().st_size / 1024 / 1024
if size_mb < 1:
    print(f'WARNING: Backup size too small: {size_mb:.1f} MB')
    sys.exit(1)
print(f'OK: Latest backup {latest.name} ({size_mb:.1f} MB, {age} old)')
" >> /var/log/azad_backup_health.log 2>&1