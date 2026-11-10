from datetime import datetime, timezone as datetime_timezone

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from ledger import greetings


@pytest.mark.parametrize("hour", range(24))
def test_greeting_is_randomly_selected_from_matching_period(hour, monkeypatch):
    expected = (greetings.MORNING_GREETINGS if 5 <= hour < 11 else
                greetings.DAYTIME_GREETINGS if 11 <= hour < 18 else
                greetings.EVENING_GREETINGS)
    # Exercise every candidate without a probabilistic test.
    for selected in expected:
        def choose(options):
            assert options == expected
            return selected
        monkeypatch.setattr(greetings, "choice", choose)
        assert greetings.greeting_for_hour(hour) == selected


@pytest.mark.django_db
def test_home_uses_japan_time_and_replaces_intro(client, monkeypatch):
    # 21:00 UTC is 06:00 the following day in Japan.
    monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 9, 16, 21, tzinfo=datetime_timezone.utc))
    monkeypatch.setattr(greetings, "choice", lambda options: options[0])
    client.force_login(User.objects.create_user("greeting-user"))
    with timezone.override("Asia/Tokyo"):
        response = client.get(reverse("chooser"))
    html = response.content.decode()
    assert "<h1>おはようございます。</h1>" in html
    assert "毎日の記録を、" not in html
    assert "暮らしの見通しに。" not in html
    assert "支出と医療費を整理して、必要なときにすぐ確認。" not in html
