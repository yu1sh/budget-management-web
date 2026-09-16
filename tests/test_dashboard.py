from datetime import date

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from ledger.models import HouseholdEntry, MedicalEntry, PaymentSource, Person


@pytest.mark.django_db
def test_home_totals_respect_period_deletion_and_expense_type(client, monkeypatch):
    monkeypatch.setattr("ledger.views.timezone.localdate", lambda: date(2026, 9, 16))
    client.force_login(User.objects.create_user("dashboard"))
    source = PaymentSource.objects.create(name="現金", kind="cash")
    for day, amount, kind, deleted in [
        ("2026-09-01", 1200, "expense", None),
        ("2026-09-02", 300, "expense", None),
        ("2026-08-01", 900, "expense", None),
        ("2026-09-03", 700, "flea_profit", None),
        ("2026-09-04", 800, "expense", timezone.now()),
    ]:
        HouseholdEntry.objects.create(
            spent_on=day, amount_yen=amount, entry_type=kind, payment_source=source,
            shop_name="店舗", description="内訳", deleted_at=deleted,
        )
    person = Person.objects.create(name="家族")
    for year, amount, deleted in [(2026, 2500, None), (2025, 800, None), (2026, 900, timezone.now())]:
        MedicalEntry.objects.create(person=person, record_year=year, provider_name="病院",
                                    paid_amount_yen=amount, deleted_at=deleted)
    response = client.get(reverse("chooser"))
    assert response.context["expense_total"] == 1500
    assert response.context["medical_total"] == 2500
    assert len(response.context["recent_entries"]) == 3
    assert response.context["has_payment_sources"] and response.context["has_people"]
    html = response.content.decode()
    assert "¥1,500" in html and "¥2,500" in html
    assert "最初の入力の前に" not in html


@pytest.mark.django_db
def test_empty_home_guides_first_entry(client):
    client.force_login(User.objects.create_user("new-user"))
    response = client.get(reverse("chooser"))
    assert response.context["expense_total"] == response.context["medical_total"] == 0
    html = response.content.decode()
    assert "支払い元を登録" in html and "医療費の対象者を登録" in html
    assert "今月の記録はまだありません" in html
