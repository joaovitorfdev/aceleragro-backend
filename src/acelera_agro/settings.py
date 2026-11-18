"""Django settings for Acelera Agro."""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent.parent

load_dotenv(REPO_ROOT / ".env")
load_dotenv(BASE_DIR.parent / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-dev-only-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "storages",
    "ninja",
    "acelera_agro.tenants",
    "acelera_agro.accounts",
    "acelera_agro.catalog",
    "acelera_agro.proposals",
    "acelera_agro.documents",
    "acelera_agro.extraction",
    "acelera_agro.activities",
    "acelera_agro.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "acelera_agro.accounts.middleware.IdempotencyMiddleware",
    "acelera_agro.accounts.middleware.TenantContextMiddleware",
]

ROOT_URLCONF = "acelera_agro.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "acelera_agro.wsgi.application"
ASGI_APPLICATION = "acelera_agro.asgi.application"

TESTING = (
    "test" in sys.argv
    or "pytest" in sys.modules
    or os.getenv("DJANGO_TESTING", "").lower() in {"1", "true", "yes"}
)

if TESTING or not os.getenv("DATABASE_URL"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3" if not TESTING else ":memory:",
        }
    }
else:
    DATABASES = {
        "default": dj_database_url.config(
            default=os.getenv("DATABASE_URL"),
            conn_max_age=600,
        )
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
LANGUAGES = [
    ("pt-br", "Português (Brasil)"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR.parent / "locale"]
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
CORS_ALLOW_CREDENTIALS = True

# S3 / MinIO
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "minioadmin")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin")
AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME", "acelera-agro")
AWS_S3_ENDPOINT_URL = os.getenv("AWS_S3_ENDPOINT_URL", "http://localhost:9000")
AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", "sa-east-1")
AWS_S3_SIGNATURE_VERSION = "s3v4"
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True
AWS_S3_FILE_OVERWRITE = False

if TESTING:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3boto3.S3Boto3Storage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }

# JWT
JWT_SECRET = os.getenv("JWT_SECRET", SECRET_KEY)
JWT_ALGORITHM = "HS256"
# Access default 8h (field day); refresh cookie still rotates via /api/auth/refresh.
JWT_ACCESS_TTL = timedelta(minutes=int(os.getenv("JWT_ACCESS_TTL_MINUTES", "480")))
JWT_REFRESH_TTL = timedelta(days=int(os.getenv("JWT_REFRESH_TTL_DAYS", "7")))
JWT_REFRESH_COOKIE_NAME = "refresh_token"
JWT_REFRESH_COOKIE_PATH = "/api/auth"
JWT_REFRESH_COOKIE_HTTPONLY = True
JWT_REFRESH_COOKIE_SECURE = not DEBUG
JWT_REFRESH_COOKIE_SAMESITE = "Lax"

EXTRACTION_PROVIDER = os.getenv("EXTRACTION_PROVIDER", "stub")
# hybrid = text-layer router + Gemini vision for photos/scans
EXTRACTION_VISION_PROVIDER = os.getenv("EXTRACTION_VISION_PROVIDER", "gemini")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
EXTRACTION_MIN_TEXT_CHARS = int(os.getenv("EXTRACTION_MIN_TEXT_CHARS", "80"))
EXTRACTION_VISION_MAX_SIDE_PX = int(os.getenv("EXTRACTION_VISION_MAX_SIDE_PX", "1600"))
EXTRACTION_HTTP_TIMEOUT_SECONDS = float(os.getenv("EXTRACTION_HTTP_TIMEOUT_SECONDS", "60"))
DEVICE_LIMIT_PER_OFFICE = int(os.getenv("DEVICE_LIMIT_PER_OFFICE", "5"))
IDEMPOTENCY_TTL_SECONDS = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "86400"))

NINJA_PAGINATION_CLASS = "ninja.pagination.LimitOffsetPagination"
