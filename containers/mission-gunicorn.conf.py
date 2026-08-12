import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = 1
worker_class = "gthread"
threads = 2
timeout = int(os.environ.get("NIGHTWATCH_REQUEST_TIMEOUT", "30"))
graceful_timeout = 10
keepalive = 5
accesslog = "-"
errorlog = "-"
capture_output = True
