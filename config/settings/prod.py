import os
import re

import dj_database_url
import sentry_sdk

from .base import *  # noqa: F401, F403

DEBUG = False

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")

DATABASES = {
    "default": dj_database_url.config(
        conn_max_age=600,
        conn_health_checks=True,
    ),
}

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

RECEIPT_EXTRACTOR = os.environ.get("RECEIPT_EXTRACTOR", "anthropic")

# --- Sentry ---
_TOKEN_RE = re.compile(r"/[bs]/([0-9a-f]{16,64})/")


def _scrub_tokens(event, hint):
    if request := event.get("request"):
        for key in ("url", "path_info"):
            if val := request.get(key):
                request[key] = _TOKEN_RE.sub(
                    lambda m: m.group().replace(m.group(1), m.group(1)[:8] + "..."),
                    val,
                )
    return event


if _dsn := os.environ.get("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=_dsn,
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.1")),
        before_send=_scrub_tokens,
    )

# --- Logging ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "token_redaction": {"()": "core.logging.TokenRedactionFilter"},
    },
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "fmt": "%(asctime)s %(name)s %(levelname)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["token_redaction"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "bills": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "receipts": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# --- Cloudflare R2 storage ---
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
AWS_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
AWS_STORAGE_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "splitsnap")
AWS_S3_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL", "")
AWS_S3_REGION_NAME = "auto"
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True
AWS_PRESIGNED_EXPIRY = 300
