#!/bin/bash
# جدولة المهام على المضيف (crontab) — Azad E-School
#
# التركيب:
#   APP_DIR=/opt/azad-e-school VENV_DIR=/opt/azad-e-school/.venv \
#     crontab scripts/cron_jobs.sh
# أو انسخ المحتوى إلى `crontab -e` بعد ضبط APP_DIR/VENV_DIR.
#
# كل سطر يستدعي scripts/scheduled_jobs.sh (مصدر واحد للأوامر)، وكل أمر قابل
# للتشغيل يدوياً بنفس الشكل:
#   APP_DIR=/opt/azad-e-school scripts/scheduled_jobs.sh pending-payments
#
# لا أسرار هنا: الأسرار تُقرأ من .env بواسطة السكربت نفسه، والمستخدم
# المطلوب لقاعدة البيانات هو دور التطبيق لا `postgres` (مبدأ أقل صلاحية).
# للنشر بالحاويات استخدم خدمة `scheduler` في deploy/docker-compose.production.yml،
# وللنشر بـ systemd استخدم deploy/azad-e-school-cron.timer — كلها تستدعي نفس السكربت.

SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
APP_DIR=/opt/azad-e-school
VENV_DIR=/opt/azad-e-school/.venv
JOBS=${APP_DIR}/scripts/scheduled_jobs.sh

# ============================================================
# المدفوعات والاشتراكات
# ============================================================

# دفعات معلّقة تجاوزت المهلة (24 ساعة) → expired
*/5 * * * * "${JOBS}" pending-payments >> /var/log/azad_payment_cleanup.log 2>&1

# اشتراكات انتهت صلاحيتها → expired (كل ساعة)
0 * * * * "${JOBS}" expire-subscriptions >> /var/log/azad_subscriptions.log 2>&1

# تذكيرات التجديد (7/3/1 أيام) — 7:00 صباحاً
0 7 * * * "${JOBS}" daily-reminders >> /var/log/azad_reminders.log 2>&1

# تنبيه غياب اليوم لوليا الأمر (AZ-P2-12) — 7:30 صباحاً
30 7 * * * "${JOBS}" absence-alerts >> /var/log/azad_absence_alerts.log 2>&1

# ============================================================
# النسخ الاحتياطي (الاحتفاظ والتنظيف داخل scripts/backup.py)
# ============================================================

# نسخة يومية 2:30 صباحاً
30 2 * * * "${JOBS}" backup >> /var/log/azad_backup.log 2>&1

# فحص حداثة النسخة 5:00 صباحاً (رمز خروج 1 إن كانت ناقصة/قديمة)
0 5 * * * "${JOBS}" backup-health >> /var/log/azad_backup_health.log 2>&1

# ============================================================
# مراقبة الذكاء الاصطناعي
# ============================================================

# تقرير استخدام يومي 6:00 صباحاً
0 6 * * * "${JOBS}" ai-usage-report >> /var/log/azad_ai_daily.log 2>&1

# تنبيه الميزانية أسبوعياً (الاثنين 9:00) — يُخرج رمز 1 عند تجاوز 80%
0 9 * * 1 "${JOBS}" ai-budget-alert >> /var/log/azad_ai_budget.log 2>&1
