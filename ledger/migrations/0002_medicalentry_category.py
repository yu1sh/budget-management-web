from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="medicalentry",
            name="category",
            field=models.CharField(
                choices=[("hospital", "病院"), ("pharmacy", "薬局"), ("transport", "交通費")],
                default="hospital",
                max_length=20,
            ),
        ),
    ]
