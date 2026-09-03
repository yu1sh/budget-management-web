from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0008_paymentsource_closing_day_paymentsource_deleted_at_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="paymentsource",
            name="unique_source_name_per_kind",
        ),
        migrations.AddConstraint(
            model_name="paymentsource",
            constraint=models.UniqueConstraint(
                condition=Q(deleted_at__isnull=True),
                fields=("kind", "name"),
                name="unique_source_name_per_kind",
            ),
        ),
    ]
