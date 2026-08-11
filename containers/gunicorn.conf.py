import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = 1
worker_class = "gthread"
threads = 4
timeout = 30
graceful_timeout = 10
keepalive = 5
accesslog = "-"
errorlog = "-"
capture_output = True
