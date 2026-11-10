import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "3"))
timeout = 90  # receipt extraction can take up to 2 x 45 s model calls
accesslog = None  # request telemetry comes from OpenTelemetry + structured app logs
