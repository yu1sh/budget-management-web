from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
from django.conf import settings
from django.db import connection
from django.core.management.base import BaseCommand
from ledger.models import HouseholdEntry, MedicalEntry
from ledger.services import export_household_month, export_medical_all, export_medical_person


class Command(BaseCommand):
    help = "Regenerate CSV mirrors and retain 30 daily local backups."

    def handle(self, *args, **kwargs):
        months = HouseholdEntry.objects.filter(deleted_at__isnull=True).values_list("spent_on__year", "spent_on__month").distinct()
        for year, month in months:
            export_household_month(year, month)
        years = set(MedicalEntry.objects.filter(deleted_at__isnull=True).values_list("record_year", flat=True))
        for year in years:
            export_medical_all(year)
            for person_id in MedicalEntry.objects.filter(record_year=year, deleted_at__isnull=True).values_list("person_id", flat=True).distinct():
                export_medical_person(year, person_id)
        root = Path(settings.RUNTIME_DIR)
        target = root / "backups" / datetime.now().strftime("%Y-%m-%d")
        target.mkdir(parents=True, exist_ok=True)
        if (root / "db.sqlite3").exists():
            # SQLite's backup API obtains a consistent snapshot while the app is
            # writing; copying the live file can otherwise produce a corrupt DB.
            connection.ensure_connection()
            destination = sqlite3.connect(target / "db.sqlite3")
            try:
                connection.connection.backup(destination)
            finally:
                destination.close()
        if (root / "csv").exists():
            shutil.copytree(root / "csv", target / "csv", dirs_exist_ok=True)
        backups = sorted((root / "backups").glob("20??-??-??"))
        for old in backups[:-30]:
            shutil.rmtree(old)
        self.stdout.write(self.style.SUCCESS(f"バックアップを保存しました: {target}"))
