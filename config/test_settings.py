"""Explicitly safe settings used only by pytest."""
import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-not-for-production")
os.environ.setdefault("DEBUG", "1")
os.environ.setdefault("SECURE_SSL_REDIRECT", "0")

from .settings import *  # noqa: F401,F403
