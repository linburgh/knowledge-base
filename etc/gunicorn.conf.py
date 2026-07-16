import os


bind = f"0.0.0.0:{os.environ.get('APP_PORT', '28003')}"
workers = int(os.environ.get("WORKERS_NUM", "2"))
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
capture_output = True

