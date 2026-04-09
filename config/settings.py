import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# --- SECURITY ---
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-fallback-key")
DEBUG = os.getenv("DEBUG", "False") == "True"

# Combine your custom domain with Railway's internal health check domain
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(",")
ALLOWED_HOSTS.append("healthcheck.railway.app")
ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS if host.strip()]

# CSRF Trusted Origins must include the protocol (https://)
raw_origins = os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
CSRF_TRUSTED_ORIGINS = [
    origin if origin.startswith("http") else f"https://{origin.strip()}"
    for origin in raw_origins
    if origin.strip()
]

# --- APP DEFINITION ---
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.gis",
    "django.contrib.staticfiles",
    "rest_framework",
    "knox",
    "corsheaders",
    "apps.user.apps.UsersConfig",
    "apps.core.apps.CoreConfig",
    "apps.customer.apps.CustomerConfig",
    "apps.provider.apps.ProviderConfig",
    "apps.staff.apps.StaffConfig",
    "apps.booking.apps.BookingConfig",
    "django_extensions",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "config.wsgi.application"


# --- DATABASE (PostGIS) ---
def _parse_db_url(url):
    if not url:
        return None
    p = urlparse(url)
    return {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": p.path.lstrip("/"),
        "USER": p.username,
        "PASSWORD": p.password,
        "HOST": p.hostname,
        "PORT": str(p.port or 5432),
    }


database_url = os.getenv("DATABASE_URL")
if database_url:
    DATABASES = {"default": _parse_db_url(database_url)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": os.getenv("DB_NAME", "snapfix_db"),
            "USER": os.getenv("DB_USER", "postgres"),
            "PASSWORD": os.getenv("DB_PASSWORD", "postgres"),
            "HOST": os.getenv("DB_HOST", "db"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }

# Enable connection pooling in production
if not DEBUG:
    DATABASES["default"]["CONN_MAX_AGE"] = 60

# --- STATIC & MEDIA ---
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Whitenoise handles static file serving when DEBUG=False
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# --- AUTH ---
AUTH_USER_MODEL = "user.User"
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- LOGGING (Production Fixed) ---
# We removed FileHandlers to avoid permission issues. Logs go to Console for Railway.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

# --- REST & CORS ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["knox.auth.TokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 10,
}

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost(:\d+)?$",
    r"^http://127\.0\.0\.1(:\d+)?$",
    r"^exp://.*$",
]
CORS_ALLOW_CREDENTIALS = True

# --- INTERNATIONALIZATION ---
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- STRIPE ---
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_CURRENCY = "egp"
