"""Settings for a private, self-hosted installation."""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIR = Path(os.environ.get("RUNTIME_DIR", BASE_DIR / "runtime"))
RUNTIME_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)

DEBUG = os.environ.get("DEBUG", "0") == "1"
_DEFAULT_SECRET_KEY = "unsafe-development-key-change-me"
_DEFAULT_SECRET_KEYS = {_DEFAULT_SECRET_KEY, "replace-with-a-long-random-value"}
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _DEFAULT_SECRET_KEY)
if not DEBUG and SECRET_KEY in _DEFAULT_SECRET_KEYS:
    raise RuntimeError("DEBUG=0 requires a unique DJANGO_SECRET_KEY. Run ./setup.sh or configure .env.")
ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [u for u in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if u]

INSTALLED_APPS = [
    "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions",
    "django.contrib.messages", "django.contrib.staticfiles", "ledger",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
              "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": RUNTIME_DIR / "db.sqlite3"}}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]
LANGUAGE_CODE = "ja"
TIME_ZONE = "Asia/Tokyo"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = RUNTIME_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": str(RUNTIME_DIR / "cache"),
        "OPTIONS": {"MAX_ENTRIES": 10_000},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "chooser"
LOGOUT_REDIRECT_URL = "login"
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 12
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "0") == "1"
# Caddy sets this header for reverse-proxied HTTPS requests. Without it, Django
# would see HTTP and redirect every request back to the same HTTPS URL.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
# No remote scripts, fonts, analytics, or media are loaded by this application.
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
