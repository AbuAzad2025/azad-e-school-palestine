"""إعدادات Gunicorn للإنتاج (HTTPS خلف الوكيل)."""

import os

bind = "0.0.0.0:8000"
workers = int(os.getenv("GUNICORN_WORKERS", "3"))
timeout = 60
accesslog = "-"
errorlog = "-"

# أمني: السماح بـ X-Forwarded-For فقط من وكيل WebSocket المحلي أو عنوان الوكيل الفعلي
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1")

# إعادة تدوير العمال لتجنب تسرب الذاكرة
max_requests = 1000
max_requests_jitter = 50

# الحفاظ على الاتصالات مع الوكيل
keepalive = 5
