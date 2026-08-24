import os
from pathlib import Path
import subprocess
import sys
import pytest
from django.contrib.auth.models import User
from django.conf import settings
from django.urls import reverse
from ledger.forms import HouseholdEntryForm, MedicalBatchForm, MedicalEntryForm, PaymentLinkForm, PaymentSourceForm, PersonForm
from ledger.models import HouseholdEntry, MedicalEntry, MedicalVisit, PaymentSource, Person
from ledger.services import recalculate_medical
from ledger.views import _month, _year

@pytest.fixture
def user(db):
    return User.objects.create_user("tester", password="safe-password-123")

@pytest.fixture
def sources(db):
    card = PaymentSource.objects.create(kind="credit_card", name="サンプルカード")
    code = PaymentSource.objects.create(kind="code_payment", name="サンプル決済", linked_source=card)
    return card, code

@pytest.mark.django_db
def test_login_then_chooser(client, user):
    assert client.get(reverse("chooser")).status_code == 302
    response = client.post(reverse("login"), {"username": "tester", "password": "safe-password-123"})
    assert response.status_code == 302 and response.url == reverse("chooser")

@pytest.mark.django_db
def test_household_entry_snapshots_and_csv(client, user, sources):
    card, code = sources
    client.force_login(user)
    response = client.post(reverse("household"), {"spent_on": "2026-08-05", "shop_name": "テスト店", "description": "食費", "amount_yen": 1200, "payment_source": code.id, "note": ""})
    assert response.status_code == 302
    entry = HouseholdEntry.objects.get()
    assert entry.linked_source == card and entry.linked_source_name_snapshot == "サンプルカード"
    path = Path(settings.RUNTIME_DIR) / "csv" / "household" / "2026" / "2026-08.csv"
    assert path.exists() and "テスト店" in path.read_text(encoding="utf-8-sig")
    assert client.get(reverse("source_detail", args=[card.id]) + "?month=2026-08").context["funded_total"] == 1200


@pytest.mark.django_db
def test_household_payment_source_snapshot_links_to_each_source_detail(client, user, sources):
    card, code = sources
    bank = PaymentSource.objects.create(kind=PaymentSource.Kind.BANK, name="テスト銀行")
    point = PaymentSource.objects.create(kind=PaymentSource.Kind.POINT, name="テストポイント")
    cash = PaymentSource.objects.create(kind=PaymentSource.Kind.CASH, name="現金")
    all_sources = [card, code, bank, point, cash]
    for index, source in enumerate(all_sources, start=1):
        HouseholdEntry.objects.create(
            spent_on="2026-08-10", shop_name=f"店舗{index}", description="テスト", amount_yen=index,
            payment_source=source, payment_source_name_snapshot=f"入力時{source.name}",
            payment_source_kind_snapshot=source.kind,
        )
    client.force_login(user)
    html = client.get(reverse("household") + "?month=2026-08").content.decode()
    for source in all_sources:
        href = reverse("source_detail", args=[source.id]) + "?month=2026-08"
        assert f'href="{href}"' in html
        assert f">入力時{source.name}</a>" in html
    css = Path("ledger/static/ledger/site.css").read_text()
    assert ".payment-source-link" in css and ".print-table a" in css

@pytest.mark.django_db
def test_household_edit_keeps_original_snapshots_when_source_unchanged(sources):
    card, code = sources
    entry = HouseholdEntry.objects.create(spent_on="2026-08-05", shop_name="テスト店", description="食費", amount_yen=100,
        payment_source=code, payment_source_name_snapshot="入力時決済", payment_source_kind_snapshot=code.kind,
        linked_source=card, linked_source_name_snapshot="入力時カード")
    code.name, card.name = "変更後決済", "変更後カード"; code.save(); card.save()
    form = HouseholdEntryForm({"spent_on": "2026-08-05", "shop_name": "テスト店", "description": "食費", "amount_yen": 100,
        "payment_source": code.id, "note": "修正"}, instance=entry)
    assert form.is_valid(); form.save(); entry.refresh_from_db()
    assert (entry.payment_source_name_snapshot, entry.linked_source_name_snapshot) == ("入力時決済", "入力時カード")

@pytest.mark.django_db
def test_medical_running_total_recalculates(client, user):
    person = Person.objects.create(name="テスト対象者")
    first = MedicalEntry.objects.create(person=person, record_year=2026, provider_name="テスト病院", paid_amount_yen=1000)
    second = MedicalEntry.objects.create(person=person, record_year=2026, provider_name="テスト薬局", paid_amount_yen=500)
    recalculate_medical(person.id, 2026)
    first.refresh_from_db(); second.refresh_from_db()
    assert (first.cumulative_amount_yen, second.cumulative_amount_yen) == (1000, 1500)
    first.paid_amount_yen = 2000; first.save(); recalculate_medical(person.id, 2026); second.refresh_from_db()
    assert second.cumulative_amount_yen == 2500


@pytest.mark.django_db
def test_hospital_page_creates_each_completed_category_and_csv(client, user):
    person = Person.objects.create(name="医療費テスト対象者")
    client.force_login(user)
    response = client.post(reverse("medical_hospital_detail", args=[person.id]) + "?year=2026&name=テスト病院", {
        "visited_on": "2026-08-10",
        "hospital_amount": "1000",
        "pharmacy_name": "テスト薬局",
        "pharmacy_amount": "300",
        "transport_method": "電車",
        "transport_amount": "200",
    })
    assert response.status_code == 302
    entries = list(MedicalEntry.objects.filter(person=person).order_by("created_at", "id"))
    assert [(entry.category, entry.provider_name, entry.paid_amount_yen) for entry in entries] == [
        (MedicalEntry.Category.HOSPITAL, "テスト病院", 1000),
        (MedicalEntry.Category.PHARMACY, "テスト薬局", 300),
        (MedicalEntry.Category.TRANSPORT, "電車", 200),
    ]
    assert [entry.cumulative_amount_yen for entry in entries] == [1000, 1300, 1500]
    csv_path = Path(settings.RUNTIME_DIR) / "csv" / "medical" / "2026" / f"person-{person.id}.csv"
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    assert "区分" in csv_text and "病院" in csv_text and "薬局" in csv_text and "交通費" in csv_text


@pytest.mark.django_db
def test_medical_visit_is_one_main_row_and_hospital_page_shows_attached_details(client, user):
    person = Person.objects.create(name="受診記録対象者")
    client.force_login(user)
    response = client.post(reverse("medical_hospital_detail", args=[person.id]) + "?year=2026&name=受診先病院", {
        "visited_on": "2026-08-15",
        "hospital_amount": "1200",
        "pharmacy_name": "付随薬局", "pharmacy_amount": "400",
        "transport_method": "地下鉄", "transport_amount": "180",
    })
    assert response.status_code == 302
    visit = MedicalVisit.objects.get(person=person)
    assert (visit.visited_on.isoformat(), visit.hospital_name) == ("2026-08-15", "受診先病院")
    assert list(visit.entries.values_list("category", "provider_name", "paid_amount_yen")) == [
        ("hospital", "受診先病院", 1200), ("pharmacy", "付随薬局", 400), ("transport", "地下鉄", 180),
    ]
    main = client.get(reverse("medical_person", args=[person.id]) + "?year=2026")
    assert main.context["visits"].count() == 1
    html = main.content.decode()
    assert "日付</th>" in html and "病院名/薬局名/交通手段" in html and "¥1780" in html
    assert "受診先病院" in html and "付随薬局" in html and "地下鉄" in html
    assert "category-hospital" in html and "category-pharmacy" in html and "category-transport" in html
    assert reverse("medical_hospital_detail", args=[person.id]) in html
    assert "病院を新規追加" in html and "病院を選択" in html
    detail = client.get(reverse("medical_hospital_detail", args=[person.id]) + "?year=2026&name=受診先病院")
    assert detail.status_code == 200
    detail_html = detail.content.decode()
    assert "付随薬局" in detail_html and "地下鉄" in detail_html
    assert 'data-selectable-table' in detail_html and 'data-range-mode' in detail_html
    assert 'data-print-range' in detail_html and 'data-clear-range' in detail_html
    assert 'data-print-title' in detail_html and "病院別明細" in detail_html


@pytest.mark.django_db
def test_medical_visit_edit_updates_attached_details_and_delete_is_logical(client, user):
    person = Person.objects.create(name="編集受診記録対象者")
    visit = MedicalVisit.objects.create(person=person, record_year=2026, visited_on="2026-01-01", hospital_name="旧病院")
    MedicalEntry.objects.create(person=person, visit=visit, record_year=2026, category="hospital", provider_name="旧病院", paid_amount_yen=100)
    MedicalEntry.objects.create(person=person, visit=visit, record_year=2026, category="pharmacy", provider_name="旧薬局", paid_amount_yen=50)
    client.force_login(user)
    response = client.post(reverse("medical_visit_edit", args=[visit.id]), {
        "visited_on": "2026-02-02", "hospital_name": "新病院", "hospital_amount": "300",
        "pharmacy_name": "", "pharmacy_amount": "", "transport_method": "バス", "transport_amount": "120",
    })
    assert response.status_code == 302
    visit.refresh_from_db()
    assert (visit.visited_on.isoformat(), visit.hospital_name) == ("2026-02-02", "新病院")
    assert list(visit.entries.filter(deleted_at__isnull=True).values_list("category", "provider_name", "paid_amount_yen")) == [
        ("hospital", "新病院", 300), ("transport", "バス", 120),
    ]
    assert client.post(reverse("medical_visit_delete", args=[visit.id])).status_code == 302
    visit.refresh_from_db()
    assert visit.deleted_at is not None
    assert not visit.entries.filter(deleted_at__isnull=True).exists()


@pytest.mark.django_db
def test_hospital_navigation_groups_only_one_person_and_excludes_deleted_records(client, user):
    first = Person.objects.create(name="病院別対象者A")
    second = Person.objects.create(name="病院別対象者B")
    visit_a1 = MedicalVisit.objects.create(person=first, record_year=2026, visited_on="2026-01-03", hospital_name="同名病院")
    MedicalEntry.objects.create(person=first, visit=visit_a1, record_year=2026, category="hospital", provider_name="同名病院", paid_amount_yen=100)
    MedicalEntry.objects.create(person=first, visit=visit_a1, record_year=2026, category="pharmacy", provider_name="付随薬局", paid_amount_yen=20)
    visit_a2 = MedicalVisit.objects.create(person=first, record_year=2026, visited_on="2026-02-03", hospital_name="同名病院")
    MedicalEntry.objects.create(person=first, visit=visit_a2, record_year=2026, category="hospital", provider_name="同名病院", paid_amount_yen=300)
    deleted = MedicalVisit.objects.create(person=first, record_year=2026, visited_on="2026-03-03", hospital_name="除外病院", deleted_at="2026-03-04T00:00:00Z")
    MedicalEntry.objects.create(person=first, visit=deleted, record_year=2026, category="hospital", provider_name="除外病院", paid_amount_yen=999)
    standalone = MedicalVisit.objects.create(person=first, record_year=2026, visited_on="2026-04-03", hospital_name="")
    MedicalEntry.objects.create(person=first, visit=standalone, record_year=2026, category="pharmacy", provider_name="旧単独薬局", paid_amount_yen=50)
    visit_b = MedicalVisit.objects.create(person=second, record_year=2026, visited_on="2026-01-03", hospital_name="同名病院")
    MedicalEntry.objects.create(person=second, visit=visit_b, record_year=2026, category="hospital", provider_name="同名病院", paid_amount_yen=700)
    client.force_login(user)

    chooser = client.get(reverse("medical_hospitals") + "?year=2026")
    assert chooser.status_code == 302 and chooser.url == reverse("medical") + "?year=2026"
    listing = client.get(reverse("medical_person", args=[first.id]) + "?year=2026")
    assert listing.status_code == 200
    hospitals = list(listing.context["hospitals"])
    assert hospitals == [{"hospital_name": "同名病院", "total": 420, "visit_count": 2}]
    html = listing.content.decode()
    assert "病院名が不明な旧単独記録が1件" in html
    assert "除外病院" not in html and "同名病院" in html
    detail = client.get(reverse("medical_hospital_detail", args=[first.id]) + "?year=2026&name=同名病院")
    assert detail.status_code == 200
    detail_html = detail.content.decode()
    assert "付随薬局" in detail_html and second.name not in detail_html
    assert 'data-selectable-table' in detail_html and 'data-print-title' in detail_html


@pytest.mark.django_db
def test_new_hospital_navigation_creates_no_empty_visit_and_validates_name(client, user):
    person = Person.objects.create(name="病院追加対象者")
    client.force_login(user)
    add_url = reverse("medical_hospital_add", args=[person.id]) + "?year=2026"
    response = client.post(add_url, {"hospital_name": "新規&病院"})
    assert response.status_code == 302
    assert "name=%E6%96%B0%E8%A6%8F%26%E7%97%85%E9%99%A2" in response.url
    assert MedicalVisit.objects.filter(person=person).count() == 0
    assert client.get(response.url).status_code == 200
    empty = client.post(add_url, {"hospital_name": ""})
    too_long = client.post(add_url, {"hospital_name": "あ" * 151})
    assert empty.status_code == too_long.status_code == 302
    assert MedicalVisit.objects.filter(person=person).count() == 0


@pytest.mark.django_db
def test_hospital_page_allows_hospital_amount_to_be_omitted(client, user):
    person = Person.objects.create(name="薬局のみ対象者")
    client.force_login(user)
    response = client.post(reverse("medical_hospital_detail", args=[person.id]) + "?year=2026&name=選択済み病院", {
        "visited_on": "2026-08-11",
        "hospital_amount": "",
        "pharmacy_name": "テスト薬局",
        "pharmacy_amount": "850",
        "transport_method": "",
        "transport_amount": "",
    })
    assert response.status_code == 302
    entry = MedicalEntry.objects.get(person=person)
    visit = MedicalVisit.objects.get(person=person)
    assert visit.hospital_name == "選択済み病院"
    assert (entry.category, entry.provider_name, entry.paid_amount_yen) == (
        MedicalEntry.Category.PHARMACY, "テスト薬局", 850
    )


@pytest.mark.django_db
def test_hospital_page_rejects_partial_pairs_and_fully_empty_submission(client, user):
    person = Person.objects.create(name="不完全入力対象者")
    client.force_login(user)
    url = reverse("medical_hospital_detail", args=[person.id]) + "?year=2026&name=選択済み病院"
    partial = client.post(url, {
        "visited_on": "2026-08-12",
        "hospital_amount": "",
        "pharmacy_name": "",
        "pharmacy_amount": "",
        "transport_method": "",
        "transport_amount": "400",
    })
    assert partial.status_code == 200
    assert "名称または交通手段を入力してください" in partial.content.decode()
    assert MedicalEntry.objects.filter(person=person).count() == 0

    empty = client.post(url, {
        "visited_on": "2026-08-12", "hospital_amount": "",
        "pharmacy_name": "", "pharmacy_amount": "",
        "transport_method": "", "transport_amount": "",
    })
    assert empty.status_code == 200
    assert "いずれか1項目以上を入力してください" in empty.content.decode()
    assert MedicalEntry.objects.filter(person=person).count() == 0


@pytest.mark.django_db
def test_medical_edit_can_change_category(client, user):
    person = Person.objects.create(name="編集対象者")
    entry = MedicalEntry.objects.create(
        person=person, record_year=2026, category=MedicalEntry.Category.HOSPITAL,
        provider_name="旧病院", paid_amount_yen=1000,
    )
    client.force_login(user)
    response = client.post(reverse("medical_edit", args=[entry.id]), {
        "category": MedicalEntry.Category.TRANSPORT,
        "provider_name": "バス",
        "paid_amount_yen": "500",
    })
    assert response.status_code == 302
    entry.refresh_from_db()
    assert (entry.category, entry.provider_name, entry.paid_amount_yen, entry.cumulative_amount_yen) == (
        MedicalEntry.Category.TRANSPORT, "バス", 500, 500
    )


@pytest.mark.django_db
def test_person_page_selects_hospital_before_rendering_three_input_blocks(client, user):
    person = Person.objects.create(name="表示対象者")
    client.force_login(user)
    response = client.get(reverse("medical_person", args=[person.id]) + "?year=2026")
    html = response.content.decode()
    assert response.status_code == 200
    assert 'name="hospital_name"' in html
    assert 'name="hospital_amount"' not in html
    detail = client.get(reverse("medical_hospital_detail", args=[person.id]) + "?year=2026&name=表示病院")
    detail_html = detail.content.decode()
    for field_name in ("hospital_amount", "pharmacy_name", "pharmacy_amount", "transport_method", "transport_amount"):
        assert f'name="{field_name}"' in detail_html
    assert 'name="hospital_name"' not in detail_html
    assert detail_html.count('class="medical-cost-card"') == 3

@pytest.mark.django_db
def test_protected_exports(client, user):
    url = reverse("household_export") + "?month=2026-08"
    assert client.get(url).status_code == 302
    client.force_login(user)
    response = client.get(url)
    assert response.status_code == 200 and response["Content-Disposition"].startswith("attachment;")

@pytest.mark.django_db
def test_inactive_person_is_viewable_but_cannot_accept_new_entry(client, user):
    person = Person.objects.create(name="過去記録のみ", is_active=False)
    client.force_login(user)
    response = client.get(reverse("medical_person", args=[person.id]) + "?year=2026")
    assert response.status_code == 200 and "新規入力はできません" in response.content.decode()
    assert client.post(reverse("medical_person", args=[person.id]) + "?year=2026", {"provider_name": "テスト病院", "paid_amount_yen": 100}).status_code == 403

@pytest.mark.django_db
def test_source_list_combines_card_direct_and_code_payment_paths(client, user, sources):
    card, code = sources
    HouseholdEntry.objects.create(spent_on="2026-08-01", shop_name="直接", description="食費", amount_yen=100,
        payment_source=card, payment_source_name_snapshot=card.name, payment_source_kind_snapshot=card.kind)
    HouseholdEntry.objects.create(spent_on="2026-08-02", shop_name="経由", description="食費", amount_yen=200,
        payment_source=code, payment_source_name_snapshot=code.name, payment_source_kind_snapshot=code.kind,
        linked_source=card, linked_source_name_snapshot=card.name)
    client.force_login(user)
    source = next(item for item in client.get(reverse("sources") + "?month=2026-08").context["sources"] if item.id == card.id)
    assert (source.direct_total, source.funded_total, source.month_total) == (100, 200, 300)


@pytest.mark.django_db
def test_payment_link_settings_updates_future_code_payment_source(client, user, sources):
    first_card, code = sources
    second_card = PaymentSource.objects.create(kind="credit_card", name="別のサンプルカード")
    client.force_login(user)
    page = client.get(reverse("payment_link_settings"))
    assert page.status_code == 200
    assert "コード決済の引き落とし元設定" in page.content.decode()
    response = client.post(
        reverse("payment_link_settings"),
        {"code_payment": code.id, "linked_source": second_card.id},
    )
    assert response.status_code == 302
    code.refresh_from_db()
    assert code.linked_source == second_card


@pytest.mark.django_db
def test_same_shop_can_have_multiple_breakdown_rows(client, user, sources):
    card, _ = sources
    client.force_login(user)
    common = {
        "spent_on": "2026-08-10",
        "shop_name": "同じテスト店",
        "amount_yen": 500,
        "payment_source": card.id,
        "note": "",
    }
    first = client.post(reverse("household"), {**common, "description": "食費"})
    second = client.post(reverse("household"), {**common, "description": "日用品"})
    assert first.status_code == second.status_code == 302
    entries = HouseholdEntry.objects.filter(shop_name="同じテスト店").order_by("description")
    assert entries.count() == 2
    assert set(entries.values_list("description", flat=True)) == {"食費", "日用品"}


@pytest.mark.django_db
def test_household_batch_post_creates_two_entries_total_and_csv(client, user, sources):
    card, _ = sources
    client.force_login(user)
    payload = {
        "spent_on": "2026-08-12", "shop_name": "まとめ買い店", "payment_source": card.id, "note": "週末",
        "lines-TOTAL_FORMS": "2", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "50",
        "lines-0-description": "食費", "lines-0-amount_yen": "1200",
        "lines-1-description": "日用品", "lines-1-amount_yen": "800",
    }
    response = client.post(reverse("household"), payload)
    assert response.status_code == 302
    entries = HouseholdEntry.objects.filter(shop_name="まとめ買い店").order_by("description")
    assert entries.count() == 2
    assert sum(entries.values_list("amount_yen", flat=True)) == 2000
    csv_text = (Path(settings.RUNTIME_DIR) / "csv" / "household" / "2026" / "2026-08.csv").read_text(encoding="utf-8-sig")
    assert "食費" in csv_text and "日用品" in csv_text


@pytest.mark.django_db
def test_invalid_household_batch_is_atomic_and_requires_a_breakdown(client, user, sources):
    card, _ = sources
    client.force_login(user)
    base = {
        "spent_on": "2026-08-12", "shop_name": "失敗店", "payment_source": card.id, "note": "",
        "lines-TOTAL_FORMS": "2", "lines-INITIAL_FORMS": "0", "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "50",
        "lines-0-description": "食費", "lines-0-amount_yen": "100",
        "lines-1-description": "金額だけ", "lines-1-amount_yen": "",
    }
    response = client.post(reverse("household"), base)
    assert response.status_code == 200
    assert HouseholdEntry.objects.filter(shop_name="失敗店").count() == 0
    empty = {**base, "lines-TOTAL_FORMS": "1", "lines-0-description": "", "lines-0-amount_yen": ""}
    response = client.post(reverse("household"), empty)
    assert response.status_code == 200
    assert "内訳を1行以上入力してください" in response.content.decode()
    assert HouseholdEntry.objects.filter(shop_name="失敗店").count() == 0


@pytest.mark.django_db
def test_existing_single_entry_edit_still_updates_one_entry(client, user, sources):
    card, _ = sources
    entry = HouseholdEntry.objects.create(spent_on="2026-08-12", shop_name="編集店", description="旧内訳", amount_yen=100,
        payment_source=card, payment_source_name_snapshot=card.name, payment_source_kind_snapshot=card.kind)
    client.force_login(user)
    response = client.post(reverse("household_edit", args=[entry.id]), {
        "spent_on": "2026-08-12", "shop_name": "編集店", "description": "新内訳", "amount_yen": "300", "payment_source": card.id, "note": "更新",
    })
    assert response.status_code == 302
    entry.refresh_from_db()
    assert (entry.description, entry.amount_yen, entry.note) == ("新内訳", 300, "更新")


@pytest.mark.django_db
def test_household_form_renders_batch_structure_datalist_and_source_guidance(client, user, sources):
    client.force_login(user)
    response = client.get(reverse("household"))
    html = response.content.decode()
    assert 'data-household-batch-form' in html
    assert 'name="lines-0-description"' in html and 'name="lines-0-amount_yen"' in html
    assert 'data-breakdown-template' in html and 'shop-name-suggestions' in html
    assert "支払い元が未登録です" not in html
    PaymentSource.objects.all().update(is_active=False)
    response = client.get(reverse("household"))
    assert "支払い元が未登録です" in response.content.decode()

def test_month_and_year_reject_out_of_range_values(rf):
    assert _month(rf.get("/?month=2026-13")) != (2026, 13)
    assert 2000 <= _year(rf.get("/?year=1999")) <= 2100

def test_user_labels_and_no_inline_submit_handlers():
    assert HouseholdEntryForm().fields["spent_on"].label == "日付"
    assert HouseholdEntryForm().fields["payment_source"].label == "支払い元"
    assert PaymentSourceForm().fields["linked_source"].label == "引き落とし元"
    assert PaymentLinkForm().fields["linked_source"].label == "引き落とし元"
    assert PersonForm().fields["name"].label == "対象者名"
    assert MedicalBatchForm().fields["hospital_name"].label == "病院名"
    assert MedicalBatchForm().fields["pharmacy_name"].label == "薬局名"
    assert MedicalBatchForm().fields["transport_method"].label == "交通手段"
    assert MedicalEntryForm().fields["provider_name"].label == "病院名・薬局名・交通手段"
    templates = "\n".join(path.read_text() for path in (Path("ledger/templates/ledger")).glob("*.html"))
    script = Path("ledger/static/ledger/table-print.js").read_text()
    assert "onsubmit=" not in templates
    assert "金の出どころ" not in templates
    assert "payment_link_settings" in templates
    assert "checkbox-field" in templates
    assert "data-household-batch-form" in templates and "data-add-breakdown" in templates
    assert "pointermove" in script and "elementFromPoint" in script and "dataset.confirm" in script
    site_script = Path("ledger/static/ledger/site.js").read_text()
    assert "lines-TOTAL_FORMS" in site_script and "data-remove-breakdown" in site_script
    css = Path("ledger/static/ledger/site.css").read_text()
    assert ".common-entry-grid" in css and ".breakdown-row" in css and "@media(max-width:760px)" in css
    assert ".medical-cost-grid" in css and ".medical-cost-card" in css

def test_production_settings_reject_default_secret(tmp_path):
    env = os.environ.copy()
    env.update({"DEBUG": "0", "RUNTIME_DIR": str(tmp_path)})
    env.pop("DJANGO_SECRET_KEY", None)
    result = subprocess.run([sys.executable, "-c", "import config.settings"], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and "DJANGO_SECRET_KEY" in result.stderr

def test_proxy_cache_backup_and_admin_hardening_are_configured():
    assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert settings.CACHES["default"]["BACKEND"].endswith("FileBasedCache")
    assert "admin/" not in Path("config/urls.py").read_text()
    assert "header_up X-Forwarded-Proto https" in Path("Caddyfile").read_text()
    assert ".backup(destination)" in Path("ledger/management/commands/backup_data.py").read_text()
    restore = Path("scripts/restore.sh").read_text()
    assert "docker compose run --rm --no-deps" in restore and "docker volume ls" not in restore
