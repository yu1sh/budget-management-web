from datetime import date
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.urls import reverse

from ledger.forms import BankForm, PaymentSourceForm
from ledger.models import HouseholdEntry, PaymentSource


@pytest.fixture
def billing_user(db):
    return User.objects.create_user("billing-tester", password="safe-password-123")


def make_entry(source, *, spent_on, amount_yen, shop_name, entry_type=HouseholdEntry.EntryType.EXPENSE, linked_source=None):
    return HouseholdEntry.objects.create(
        spent_on=spent_on,
        shop_name=shop_name,
        description="テスト明細",
        amount_yen=amount_yen,
        entry_type=entry_type,
        payment_source=source,
        payment_source_name_snapshot=f"入力時{source.name}",
        payment_source_kind_snapshot=source.kind,
        linked_source=linked_source,
        linked_source_name_snapshot=linked_source.name if linked_source else "",
        settlement_path_snapshot=f"入力時{source.name}",
    )


@pytest.mark.django_db
def test_statement_period_is_payment_month_based_and_clamps_leap_year_days():
    card = PaymentSource.objects.create(
        kind=PaymentSource.Kind.CREDIT,
        name="締め日カード",
        closing_day=31,
        payment_day=31,
        payment_month_offset=1,
    )
    # September payment with 翌月払い means the previous August closing
    # period, and day 31 clamps to February's leap-day when needed.
    assert card.statement_period(2026, 9) == (
        date(2026, 8, 1), date(2026, 8, 31), date(2026, 9, 30),
    )
    assert card.statement_period(2024, 3) == (
        date(2024, 2, 1), date(2024, 2, 29), date(2024, 3, 31),
    )
    assert "月末" in card.schedule_display()


@pytest.mark.django_db
def test_source_forms_validate_color_schedule_and_bank_color():
    assert PaymentSource.DEFAULT_MAIN_COLOR == "#1456A0"
    assert PaymentSource.objects.create(kind=PaymentSource.Kind.CASH, name="既定色").main_color == "#1456A0"
    assert [value for value, _label in PaymentSourceForm.DAY_CHOICES].count(31) == 1
    common = {"kind": PaymentSource.Kind.CREDIT, "name": "色カード", "main_color": "#123ABC", "is_active": "on"}
    form = PaymentSourceForm({**common, "closing_day": "15", "payment_day": "10", "payment_month_offset": "1"})
    assert form.is_valid(), form.errors
    assert form.save().main_color == "#123ABC"
    assert not PaymentSourceForm({**common, "main_color": "#123"}).is_valid()
    partial = PaymentSourceForm({**common, "closing_day": "15", "payment_day": "", "payment_month_offset": "1"})
    assert not partial.is_valid()
    assert "payment_day" in partial.errors
    bank = BankForm({"name": "色銀行", "main_color": "#AABBCC", "is_active": "on"})
    assert bank.is_valid(), bank.errors
    assert bank.save().main_color == "#AABBCC"
    deleted_bank = PaymentSource.objects.create(kind=PaymentSource.Kind.BANK, name="再利用銀行", deleted_at="2026-01-01T00:00:00Z", is_active=False)
    replacement_bank = BankForm({"name": "再利用銀行", "main_color": "#AABBCC", "is_active": "on"})
    assert replacement_bank.is_valid(), replacement_bank.errors
    assert not PaymentSourceForm({"kind": PaymentSource.Kind.BANK, "name": "不正予定", "main_color": "#AABBCC", "closing_day": "1"}).is_valid()


@pytest.mark.django_db
def test_source_delete_requires_post_and_hides_historical_source(client, billing_user):
    client.force_login(billing_user)
    card = PaymentSource.objects.create(kind=PaymentSource.Kind.CREDIT, name="履歴カード")
    make_entry(card, spent_on="2026-08-01", amount_yen=100, shop_name="履歴店")
    url = reverse("source_delete", args=[card.id])
    assert client.get(url).status_code == 405
    response = client.post(url)
    assert response.status_code == 302
    card.refresh_from_db()
    assert card.deleted_at is not None and card.is_active is False
    replacement = PaymentSource.objects.create(kind=PaymentSource.Kind.CREDIT, name="履歴カード")
    assert replacement.id != card.id
    assert card.id not in [source.id for source in client.get(reverse("sources")).context["sources"]]
    assert client.get(reverse("source_detail", args=[card.id])).status_code == 200
    assert "削除済み" in client.get(reverse("source_detail", args=[card.id])).content.decode()
    assert replacement.id in [source.id for source in client.get(reverse("sources")).context["sources"]]


@pytest.mark.django_db
def test_source_delete_hides_current_link_and_hard_deletes_unused_source(client, billing_user):
    client.force_login(billing_user)
    card = PaymentSource.objects.create(kind=PaymentSource.Kind.CREDIT, name="リンクカード")
    code = PaymentSource.objects.create(kind=PaymentSource.Kind.CODE, name="リンクコード", linked_source=card)
    response = client.post(reverse("source_delete", args=[card.id]))
    assert response.status_code == 302
    card.refresh_from_db()
    code.refresh_from_db()
    assert card.deleted_at is not None and code.linked_source_id == card.id
    unused = PaymentSource.objects.create(kind=PaymentSource.Kind.CASH, name="未使用")
    unused_id = unused.id
    assert client.post(reverse("source_delete", args=[unused_id])).status_code == 302
    assert not PaymentSource.objects.filter(id=unused_id).exists()


@pytest.mark.django_db
def test_credit_billing_includes_direct_and_code_rows_excludes_flea_and_exports(client, billing_user):
    bank = PaymentSource.objects.create(kind=PaymentSource.Kind.BANK, name="引落銀行")
    card = PaymentSource.objects.create(
        kind=PaymentSource.Kind.CREDIT, name="請求カード", linked_source=bank,
        closing_day=15, payment_day=10, payment_month_offset=1,
    )
    code = PaymentSource.objects.create(kind=PaymentSource.Kind.CODE, name="カード連携コード", linked_source=card)
    flea = PaymentSource.objects.create(kind=PaymentSource.Kind.FLEA_MARKET, name="フリマ")
    make_entry(card, spent_on="2026-08-15", amount_yen=1000, shop_name="直接店")
    make_entry(code, spent_on="2026-08-14", amount_yen=2000, shop_name="コード店", linked_source=card)
    make_entry(code, spent_on="2026-09-01", amount_yen=5000, shop_name="対象外")
    make_entry(flea, spent_on="2026-08-20", amount_yen=9000, shop_name="利益", entry_type=HouseholdEntry.EntryType.FLEA_PROFIT, linked_source=card)
    client.force_login(billing_user)
    listing = client.get(reverse("credit_card_billing") + "?month=2026-09")
    assert listing.status_code == 200
    statement = listing.context["statements"][0]
    assert statement["total"] == 3000
    assert statement["period_start"] == date(2026, 7, 16)
    assert statement["period_end"] == date(2026, 8, 15)
    assert "クレジットカード引落明細" in listing.content.decode()
    detail = client.get(reverse("credit_card_billing_detail", args=[card.id]) + "?month=2026-09")
    assert detail.context["total"] == 3000
    detail_html = detail.content.decode()
    assert "直接店" in detail_html and "コード店" in detail_html
    assert "対象外" not in detail_html and "利益" not in detail_html
    assert 'data-selectable-table' in detail_html and 'data-print-range' in detail_html
    csv_response = client.get(reverse("credit_card_billing_export", args=[card.id]) + "?month=2026-09")
    csv_text = b"".join(csv_response.streaming_content).decode("utf-8-sig")
    assert csv_response.status_code == 200 and "直接店" in csv_text and "コード店" in csv_text


@pytest.mark.django_db
def test_unconfigured_card_is_safe_and_nav_is_available(client, billing_user):
    card = PaymentSource.objects.create(kind=PaymentSource.Kind.CREDIT, name="旧カード")
    client.force_login(billing_user)
    page = client.get(reverse("credit_card_billing") + "?month=2026-09")
    assert page.status_code == 200
    assert "旧カード" in page.content.decode() and "未設定" in page.content.decode()
    detail = client.get(reverse("credit_card_billing_detail", args=[card.id]) + "?month=2026-09")
    assert detail.status_code == 200 and detail.context["total"] == 0
    assert f'href="{reverse("credit_card_billing")}"' in detail.content.decode()
    source_page = client.get(reverse("source_settings"))
    assert f'href="{reverse("credit_card_billing")}"' in source_page.content.decode()
