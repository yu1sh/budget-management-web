import os

# Django imports settings while pytest collects tests. Production settings fail
# closed without a secret; tests deliberately provide an explicit local one.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-not-for-production")
os.environ.setdefault("DEBUG", "1")
os.environ.setdefault("SECURE_SSL_REDIRECT", "0")
