from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="banner_key",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
        migrations.AddConstraint(
            model_name="organization",
            constraint=models.UniqueConstraint(
                condition=~Q(cnpj="") & Q(cnpj__isnull=False),
                fields=("cnpj",),
                name="uniq_organization_cnpj_when_set",
            ),
        ),
        migrations.AddConstraint(
            model_name="office",
            constraint=models.UniqueConstraint(
                fields=("organization", "municipality"),
                name="uniq_office_org_municipality",
            ),
        ),
    ]
