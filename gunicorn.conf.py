import os

bind = "unix:/run/gunicorn.sock"
workers = int(os.getenv("GUNICORN_WORKERS", "4"))
worker_class = "gthread"
threads = 2
timeout = 120
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
max_requests = 1000
max_requests_jitter = 50
keepalive = 5
capture_output = True
enable_stdio_inheritance = True
