import os
import multiprocessing

# Server socket binding
host = os.getenv("HOST", "0.0.0.0")
port = os.getenv("PORT", "8050")
bind = f"{host}:{port}"

# Worker processes and concurrency
# Default to 2-4 workers based on CPU cores, overrideable via WORKERS or WEB_CONCURRENCY
default_workers = max(2, min(4, multiprocessing.cpu_count()))
workers = int(os.getenv("WEB_CONCURRENCY", os.getenv("WORKERS", str(default_workers))))
worker_class = "uvicorn.workers.UvicornWorker"

# Timeouts: Generous timeout (300s) to accommodate heavy LLM generation & document parsing
timeout = int(os.getenv("GUNICORN_TIMEOUT", "300"))
graceful_timeout = 30
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))

# Logging to standard output & error for container runtime collection
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" (%(D)s µs)'

# Process title
proc_name = "ai_question_generator"

# Trust reverse-proxy headers
forwarded_allow_ips = os.getenv("TRUSTED_PROXIES", "*")
