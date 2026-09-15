from datetime import date

import pytest

from ledger.models import MedicalEntry, MedicalVisit, Person
from ledger.services import delete_medical_visit, save_medical_visit


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_visit_changes_roll_back_when_export_fails(monkeypatch, operation):
    person = Person.objects.create(name="対象者")
    visit = MedicalVisit.objects.create(
        person=person, record_year=2026,
        visited_on=date(2026, 1, 1), hospital_name="旧病院",
    )
    entry = MedicalEntry.objects.create(
        person=person, visit=visit, record_year=2026,
        category=MedicalEntry.Category.HOSPITAL,
        provider_name="旧病院", paid_amount_yen=100,
    )

    def fail_export(*args):
        raise OSError("CSV write failed")

    monkeypatch.setattr("ledger.services.export_medical_person", fail_export)
    with pytest.raises(OSError, match="CSV write failed"):
        if operation == "delete":
            delete_medical_visit(visit)
        else:
            save_medical_visit(
                person, 2026, visited_on=date(2026, 2, 2),
                hospital_name="新病院",
                entries=[(MedicalEntry.Category.HOSPITAL, "新病院", 300)],
                visit=visit if operation == "update" else None,
            )

    visit.refresh_from_db()
    entry.refresh_from_db()
    assert MedicalVisit.objects.count() == 1
    assert MedicalEntry.objects.count() == 1
    assert (visit.visited_on, visit.hospital_name, visit.deleted_at) == (
        date(2026, 1, 1), "旧病院", None,
    )
    assert (entry.provider_name, entry.paid_amount_yen, entry.deleted_at) == (
        "旧病院", 100, None,
    )
