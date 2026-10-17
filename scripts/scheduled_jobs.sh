#!/bin/bash
# AZ-P1-10: أوامر المهام المجدولة — مصدر واحد للحقيقة.
#
# يستدعيه cron المضيف (scripts/cron_jobs.sh)، وملف cron داخل الحاوية
# (deploy/crontab). السبب: كل مسار جدولة كان يكرّر الأمر بنفسه، فأي إصلاح
# يُطبَّق في مكان ويبقى الآخر معطوباً (وهو ما حدث فعلاً في AZ-P1-09). الآن
# الجدولة تحدد *متى* يعمل الأمر وهذا الملف يحدد *ماذا* يعمل.
#
# الاستعمال: scripts/scheduled_jobs.sh <job>
# المهام: pending-payments | expire-subscriptions | daily-reminders | backup
#          | ai-usage-report | ai-budget-alert | backup-health
#
# المسارات: تُشتق من موقع السكربت (تعمل على المضيف وفي الحاوية بلا تعديل)،
# ويمكن تجاوزها بـ APP_DIR / VENV_DIR.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(dirname "${SCRIPT_DIR}")}"
VENV_DIR="${VENV_DIR:-${APP_DIR}/.venv}"

if [ -x "${VENV_DIR}/bin/python" ]; then
  # نشر POSIX (مضيف Linux أو حاوية بأدوات محلية).
  PYTHON=("${VENV_DIR}/bin/python")
  FLASK=("${VENV_DIR}/bin/flask")
elif [ -x "${VENV_DIR}/Scripts/python.exe" ]; then
  # ويندوز (بيئة التطوير): venv بمخطط Scripts/ لا bin/.
  PYTHON=("${VENV_DIR}/Scripts/python.exe")
  FLASK=("${VENV_DIR}/Scripts/python.exe" -m flask)
elif [ -x /usr/local/bin/python ]; then
  # صورة الحاوية: التطبيق مثبّت نظامياً لا في venv.
  PYTHON=(/usr/local/bin/python)
  FLASK=(/usr/local/bin/flask)
else
  PYTHON=(python3)
  FLASK=(python3 -m flask)
fi

export FLASK_APP="${FLASK_APP:-run.py}"
export APP_ENV="${APP_ENV:-production}"

# الأسرار تُقرأ من .env (نفس الملف الذي يقرأه التطبيق) — لا كلمات مرور هنا.
if [ -f "${APP_DIR}/.env" ]; then
  set -a
  # shellcheck disable=SC1090,SC1091
  . "${APP_DIR}/.env"
  set +a
fi

cd "${APP_DIR}"

case "${1:-}" in
  pending-payments)
    exec "${FLASK[@]}" expire-pending-payments
    ;;
  expire-subscriptions)
    exec "${FLASK[@]}" expire-subscriptions
    ;;
  daily-reminders)
    exec "${PYTHON[@]}" "${APP_DIR}/scripts/daily_reminders.py"
    ;;
  absence-alerts)
    exec "${FLASK[@]}" send-absence-alerts
    ;;
  backup)
    exec "${SCRIPT_DIR}/cron_backup.sh"
    ;;
  ai-usage-report)
    exec "${FLASK[@]}" ai-usage-report --days 1
    ;;
  ai-budget-alert)
    # رمز خروج 1 عند تجاوز العتبة — ليُنبَّه المشغّل من cron لا من قراءة سجل.
    exec "${FLASK[@]}" ai-usage-report --days 30 --budget-threshold 80
    ;;
  backup-health)
    exec "${FLASK[@]}" backup-health --max-age-hours 25
    ;;
  *)
    echo "usage: $0 {pending-payments|expire-subscriptions|daily-reminders|absence-alerts|backup|ai-usage-report|ai-budget-alert|backup-health}" >&2
    exit 2
    ;;
esac
