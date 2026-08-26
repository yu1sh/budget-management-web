"""Data export and deterministic medical running-total helpers."""
import csv
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from .models import HouseholdEntry, MedicalEntry, MedicalVisit, PaymentSource


def csv_safe(value):
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def payment_source_kind_label(kind):
    try:
        return PaymentSource.Kind(kind).label
    except ValueError:
        # Keep historical/raw values exportable even if a retired type exists.
        return kind


def _replace_csv(path: Path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8-sig", newline="", dir=path.parent, delete=False) as tmp:
        writer = csv.writer(tmp, lineterminator="\r\n")
        writer.writerow(header)
        writer.writerows(rows)
        temp_name = tmp.name
    os.replace(temp_name, path)


def household_csv_path(year, month):
    return Path(settings.RUNTIME_DIR) / "csv" / "household" / str(year) / f"{year}-{month:02d}.csv"


def medical_csv_path(year, person_id):
    return Path(settings.RUNTIME_DIR) / "csv" / "medical" / str(year) / f"person-{person_id}.csv"


def export_household_month(year, month):
    entries = HouseholdEntry.objects.filter(spent_on__year=year, spent_on__month=month, deleted_at__isnull=True).order_by("spent_on", "created_at", "id")
    rows = [[e.id, e.spent_on.isoformat(), csv_safe(e.shop_name), csv_safe(e.description), e.amount_yen,
             e.payment_source_id, e.payment_source_kind_snapshot, csv_safe(e.payment_source_name_snapshot),
             csv_safe(e.linked_source_name_snapshot), csv_safe(e.note), e.created_at.isoformat(), e.updated_at.isoformat(),
             payment_source_kind_label(e.payment_source_kind_snapshot), e.get_entry_type_display()] for e in entries]
    _replace_csv(household_csv_path(year, month), ["id", "日付", "店名", "内訳", "金額", "支払い元ID", "支払い元種類", "支払い元名", "コード決済引き落とし元", "備考", "作成日時", "更新日時", "支払い元種類表示", "種別"], rows)


def recalculate_medical(person_id, year):
    """Store running totals per visit date, while retaining old standalone rows."""
    with transaction.atomic():
        running = 0
        visits = list(
            MedicalVisit.objects.select_for_update()
            .filter(person_id=person_id, record_year=year, deleted_at__isnull=True)
            .order_by("visited_on", "created_at", "id")
        )
        details_by_visit = {}
        if visits:
            details = MedicalEntry.objects.select_for_update().filter(
                visit__in=visits, deleted_at__isnull=True,
            ).order_by("created_at", "id")
            for entry in details:
                details_by_visit.setdefault(entry.visit_id, []).append(entry)
        standalone = list(
            MedicalEntry.objects.select_for_update().filter(
                person_id=person_id, record_year=year, visit__isnull=True, deleted_at__isnull=True,
            ).order_by("created_at", "id")
        )
        records = [
            (visit.visited_on, visit.created_at, visit.id, "visit", visit)
            for visit in visits if details_by_visit.get(visit.id)
        ] + [
            (entry.created_at.date(), entry.created_at, entry.id, "entry", entry)
            for entry in standalone
        ]
        for _date, _created, _id, kind, record in sorted(records):
            if kind == "entry":
                running += record.paid_amount_yen
                if record.cumulative_amount_yen != running:
                    MedicalEntry.objects.filter(pk=record.pk).update(cumulative_amount_yen=running)
                continue
            detail_running = running
            amount = 0
            for entry in details_by_visit[record.id]:
                amount += entry.paid_amount_yen
                detail_running += entry.paid_amount_yen
                if entry.cumulative_amount_yen != detail_running:
                    MedicalEntry.objects.filter(pk=entry.pk).update(cumulative_amount_yen=detail_running)
            running += amount
            if record.cumulative_amount_yen != running:
                MedicalVisit.objects.filter(pk=record.pk).update(cumulative_amount_yen=running)


def export_medical_person(year, person_id):
    recalculate_medical(person_id, year)
    entries = (
        MedicalEntry.objects.filter(person_id=person_id, record_year=year, deleted_at__isnull=True)
        .select_related("visit")
        .order_by("visit__visited_on", "visit__created_at", "visit__id", "created_at", "id")
    )
    rows = [[
        e.visit_id or "", e.visit.visited_on.isoformat() if e.visit_id else e.created_at.date().isoformat(),
        csv_safe(e.visit.hospital_name if e.visit_id else ""),
        e.visit.cumulative_amount_yen if e.visit_id else e.cumulative_amount_yen,
        e.id, e.get_category_display(), csv_safe(e.provider_name), e.paid_amount_yen,
        e.created_at.isoformat(), e.updated_at.isoformat(),
    ] for e in entries]
    _replace_csv(
        medical_csv_path(year, person_id),
        ["受診記録ID", "日付", "病院名", "個人累計", "明細ID", "区分", "病院名・薬局名・交通手段", "明細金額", "作成日時", "更新日時"],
        rows,
    )


def export_medical_all(year):
    person_ids = MedicalEntry.objects.filter(record_year=year, deleted_at__isnull=True).values_list("person_id", flat=True).distinct()
    for person_id in person_ids:
        recalculate_medical(person_id, year)
    entries = (
        MedicalEntry.objects.filter(record_year=year, deleted_at__isnull=True)
        .select_related("person", "visit")
        .order_by("person__name", "visit__visited_on", "visit__created_at", "visit__id", "created_at", "id")
    )
    rows = [[
        e.person_id, csv_safe(e.person.name), e.visit_id or "",
        e.visit.visited_on.isoformat() if e.visit_id else e.created_at.date().isoformat(),
        csv_safe(e.visit.hospital_name if e.visit_id else ""),
        e.visit.cumulative_amount_yen if e.visit_id else e.cumulative_amount_yen,
        e.id, e.get_category_display(), csv_safe(e.provider_name), e.paid_amount_yen,
    ] for e in entries]
    _replace_csv(
        Path(settings.RUNTIME_DIR) / "csv" / "medical" / str(year) / "all.csv",
        ["対象者ID", "対象者", "受診記録ID", "日付", "病院名", "個人累計", "明細ID", "区分", "病院名・薬局名・交通手段", "明細金額"],
        rows,
    )
