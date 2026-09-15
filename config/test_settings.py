"""Explicitly safe settings used only by pytest."""
import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-not-for-production")
os.environ.setdefault("DEBUG", "1")
os.environ.setdefault("SECURE_SSL_REDIRECT", "0")

from .settings import *  # noqa: F401,F403

# Unit tests render pages without collectstatic. Production asset delivery is
# covered separately using config.settings and a collected manifest.
STORAGES = {
    **STORAGES,
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
