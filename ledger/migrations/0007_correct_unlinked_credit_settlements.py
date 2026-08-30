from django.db import migrations, models


def correct_unlinked_direct_credit_entries(apps, schema_editor):
    """Correct only direct-card rows that 0006 could safely identify.

    Old code-payment rows with a recorded direct card remain untouched: their
    historical snapshot did not contain enough information to infer a bank.
    """
    HouseholdEntry = apps.get_model("ledger", "HouseholdEntry")
    for entry in HouseholdEntry.objects.select_related("payment_source").filter(
        payment_source__kind="credit_card",
        linked_source__isnull=True,
        settlement_source_id=models.F("payment_source_id"),
    ).iterator():
        HouseholdEntry.objects.filter(pk=entry.pk).update(
            settlement_source=None,
            settlement_source_name_snapshot="",
            settlement_path_snapshot=f"{entry.payment_source_name_snapshot} → 未設定",
        )


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0006_household_settlement_snapshots"),
    ]

    operations = [
        migrations.RunPython(correct_unlinked_direct_credit_entries, migrations.RunPython.noop),
    ]
