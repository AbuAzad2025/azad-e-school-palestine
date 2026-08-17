"""إعدادات Gunicorn للإنتاج (HTTPS خلف الوكيل)."""

bind = "0.0.0.0:8000"
workers = 3
timeout = 60
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = "*"
