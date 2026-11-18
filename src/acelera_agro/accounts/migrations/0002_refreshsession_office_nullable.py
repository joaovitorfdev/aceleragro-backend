import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="refreshsession",
            name="office",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="refresh_sessions",
                to="tenants.office",
            ),
        ),
    ]
