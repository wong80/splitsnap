import os

import dj_database_url

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
