# Generated manually to preserve the former flea-market ledger while moving it
# into the common household-entry workflow.
from django.db import migrations, models


def migrate_flea_market_transactions(apps, schema_editor):
    PaymentSource = apps.get_model("ledger", "PaymentSource")
    HouseholdEntry = apps.get_model("ledger", "HouseholdEntry")
    FleaMarketTransaction = apps.get_model("ledger", "FleaMarketTransaction")

    for item in FleaMarketTransaction.objects.all().iterator():
        source = PaymentSource.objects.get(pk=item.payment_source_id)
        entry_type = "flea_profit" if item.transaction_type == "profit" else "flea_withdrawal"
        description = "フリマ利益" if item.transaction_type == "profit" else "フリマ出金"
        entry = HouseholdEntry.objects.create(
            spent_on=item.transacted_on,
            shop_name=source.name[:150],
            description=description,
            amount_yen=item.amount_yen,
            entry_type=entry_type,
            payment_source_id=item.payment_source_id,
            payment_source_name_snapshot=source.name,
            payment_source_kind_snapshot=source.kind,
            linked_source=None,
            linked_source_name_snapshot="",
            note=item.note,
            deleted_at=item.deleted_at,
        )
        # Preserve the historical sort order/audit times despite auto_now fields.
        HouseholdEntry.objects.filter(pk=entry.pk).update(
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0004_alter_paymentsource_kind_fleamarkettransaction"),
    ]

    operations = [
        migrations.AddField(
            model_name="householdentry",
            name="entry_type",
            field=models.CharField(
                choices=[
                    ("expense", "通常支出"),
                    ("flea_profit", "フリマ利益"),
                    ("flea_withdrawal", "フリマ出金"),
                ],
                default="expense",
                max_length=20,
            ),
        ),
        migrations.RunPython(migrate_flea_market_transactions, migrations.RunPython.noop),
        migrations.DeleteModel(name="FleaMarketTransaction"),
    ]
