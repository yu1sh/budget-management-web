import os
import subprocess
import sys
from textwrap import dedent


def test_production_pages_use_versioned_and_served_assets(tmp_path):
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "DJANGO_SECRET_KEY": "static-assets-test-only",
        "DEBUG": "0",
        "RUNTIME_DIR": str(tmp_path),
        "ALLOWED_HOSTS": "testserver",
        "SECURE_SSL_REDIRECT": "0",
    }
    script = dedent('''
        import re
        import django
        django.setup()
        from django.core.management import call_command
        from django.contrib.staticfiles.storage import staticfiles_storage
        from django.template.loader import render_to_string
        from django.test import Client, RequestFactory
        from types import SimpleNamespace

        call_command("collectstatic", interactive=False, verbosity=0)
        request = RequestFactory().get("/")
        request.user = SimpleNamespace(is_authenticated=True)
        html = render_to_string("ledger/chooser.html", request=request)
        client = Client()
        for filename in ("site.css", "site.js", "table-print.js"):
            url = staticfiles_storage.url("ledger/" + filename)
            stem, extension = filename.rsplit(".", 1)
            assert re.fullmatch(r"/static/ledger/" + re.escape(stem) + r"\\.[0-9a-f]{12}\\." + extension, url), url
            assert url in html
            response = client.get(url)
            assert response.status_code == 200
            body = b"".join(response.streaming_content).decode()
            if filename == "site.css":
                assert ".skip-link:focus" in body
                assert ".settings-menu-items" in body
            assert "immutable" in response["Cache-Control"]
    ''')
    result = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
