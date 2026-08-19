#!/usr/bin/env python
"""سكريبت التذكيرات اليومية — يتم تشغيله عبر cron يومياً.

يبحث عن الاشتراكات التي تنتهي صلاحيتها خلال 7، 3، أو 1 يوم
ويرسل تذكيرات بالبريد الإلكتروني.
"""

import sys
import os

# إضافة مسار المشروع
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.billing import Subscription, ReminderLog
from app.services.email import send_payment_reminder_email
from app.core.db import tx
from datetime import datetime, timedelta, UTC


def run_daily_reminders(app=None):
    """تشغيل التذكيرات اليومية للاشتراكات المنتهية قريباً."""
    if app is None:
        app = create_app()
    with app.app_context():
        now = datetime.now(UTC)

        # الأيام المستهدفة: 7، 3، 1
        target_days = [7, 3, 1]
        sent_count = 0

        for days in target_days:
            target_date = now + timedelta(days=days)
            start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)

            # البحث عن الاشتراكات النشطة التي تنتهي في اليوم المستهدف
            subs = (
                Subscription.query.filter(
                    Subscription.status == "active",
                    Subscription.end_at >= start_of_day,
                    Subscription.end_at < end_of_day,
                ).all()
            )

            reminder_type = f"{days}d"

            for sub in subs:
                # التحقق مما إذا تم إرسال تذكير لهذا الاشتراك وهذا النوع مسبقاً
                existing = ReminderLog.query.filter_by(
                    subscription_id=sub.id,
                    reminder_type=reminder_type,
                ).first()

                if existing:
                    continue  # تم الإرسال مسبقاً

                # حساب الأيام المتبقية بدقة
                delta = sub.end_at - now
                days_until = delta.days

                # إرسال الإيميل - يحتاج لتحميل العلاقات
                if send_payment_reminder_email(sub, days_until):
                    # تسجيل في السجل
                    def _log():
                        log = ReminderLog(
                            subscription_id=sub.id,
                            reminder_type=reminder_type,
                            sent_at=datetime.now(UTC),
                        )
                        db.session.add(log)
                        return log
                    tx(_log)
                    sent_count += 1
                    print(f"Sent {reminder_type} reminder for subscription {sub.id} (user {sub.user_id})")
                else:
                    print(f"Failed to send {reminder_type} reminder for subscription {sub.id}")

        print(f"Total reminders sent: {sent_count}")
        return sent_count


if __name__ == "__main__":
    run_daily_reminders()