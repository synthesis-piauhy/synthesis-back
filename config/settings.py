import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
APP_ENV = os.getenv("APP_ENV", "development")
if APP_ENV not in {"development", "test", "production"}:
    raise ImproperlyConfigured("APP_ENV deve ser development, test ou production.")
PRODUCTION = APP_ENV == "production"
if not PRODUCTION:
    load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "unsafe-development-key-change-before-production")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
if PRODUCTION:
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    if DEBUG:
        raise ImproperlyConfigured("DEBUG não pode estar ativo em produção.")
    for key in ("SECRET_KEY",):
        value = os.getenv(key, "")
        if (
            len(value) < 50
            or len(set(value)) < 10
            or any(word in value.lower() for word in ("unsafe", "troque", "change-me"))
        ):
            raise ImproperlyConfigured(f"{key} deve ser uma chave forte exclusiva de produção.")
    for key in ("ALLOWED_HOSTS", "DATABASE_URL", "PUBLIC_ORIGIN"):
        if not os.getenv(key):
            raise ImproperlyConfigured(f"{key} é obrigatório em produção.")
ALLOWED_HOSTS = [
    value for value in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if value
]
if PRODUCTION and ("*" in ALLOWED_HOSTS or "testserver" in ALLOWED_HOSTS):
    raise ImproperlyConfigured("ALLOWED_HOSTS deve conter apenas os hosts da implantação.")

PUBLIC_ORIGIN = os.getenv("PUBLIC_ORIGIN", "http://localhost:3000").rstrip("/")
if PRODUCTION and (
    urlparse(PUBLIC_ORIGIN).scheme != "https"
    or not urlparse(PUBLIC_ORIGIN).netloc
    or urlparse(PUBLIC_ORIGIN).path
    or urlparse(PUBLIC_ORIGIN).query
):
    raise ImproperlyConfigured("PUBLIC_ORIGIN deve ser uma origem HTTPS sem caminho.")
SECURE_SSL_REDIRECT = PRODUCTION
SESSION_COOKIE_SECURE = PRODUCTION
CSRF_COOKIE_SECURE = PRODUCTION
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = [PUBLIC_ORIGIN]
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "3600" if PRODUCTION else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# Deliberate single-host HSTS: subdomains and browser preload require a separate rollout.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"] if PRODUCTION else []
TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() == "true"
if TRUST_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
DATA_UPLOAD_MAX_MEMORY_SIZE = 26 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = 10
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "ninja_extra",
    "synthesis.apps.SynthesisConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "synthesis.observability.RequestLogMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "synthesis.authentication.SessionVersionMiddleware",
    "synthesis.rate_limits.RateLimitMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

database_url = os.getenv("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
if PRODUCTION:
    if not database_url.startswith(("postgres://", "postgresql://")):
        raise ImproperlyConfigured("Produção requer PostgreSQL configurado explicitamente.")
    if "sslmode=verify-full" not in database_url and os.getenv("DATABASE_LOCAL_PRIVATE", "false") != "true":
        raise ImproperlyConfigured(
            "Banco remoto requer sslmode=verify-full; banco local isolado requer DATABASE_LOCAL_PRIVATE=true."
        )
if "pytest" in sys.modules or any("pytest" in argument for argument in sys.argv):
    database_url = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{BASE_DIR / 'test.sqlite3'}"

DATABASES = {
    "default": dj_database_url.parse(
        database_url,
        conn_max_age=60,
        conn_health_checks=True,
    )
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    DATABASES["default"]["TEST"] = {"CHARSET": "UTF8", "TEMPLATE": "template0"}

AUTH_USER_MODEL = "synthesis.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Fortaleza"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", str(BASE_DIR / "media")))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = [
    value for value in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if value
]
if PRODUCTION:
    CORS_ALLOWED_ORIGINS = [PUBLIC_ORIGIN]
CORS_ALLOW_CREDENTIALS = True

if os.getenv("AWS_STORAGE_BUCKET_NAME"):
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    AWS_STORAGE_BUCKET_NAME = os.environ["AWS_STORAGE_BUCKET_NAME"]
    AWS_S3_ENDPOINT_URL = os.getenv("AWS_S3_ENDPOINT_URL")
    AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME")
    AWS_QUERYSTRING_AUTH = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "synthesis.observability.JsonFormatter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "loggers": {
        "synthesis": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO"), "propagate": False},
    },
}
