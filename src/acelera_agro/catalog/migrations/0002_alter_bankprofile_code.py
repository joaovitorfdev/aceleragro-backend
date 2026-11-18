# Generated manually for BankProfile.Code.CAIXA

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="bankprofile",
            name="code",
            field=models.CharField(
                choices=[
                    ("bb", "Banco do Brasil"),
                    ("caixa", "Caixa Econômica Federal"),
                    ("basa", "BASA"),
                    ("sicredi", "Sicredi"),
                    ("sicoob", "Sicoob"),
                ],
                max_length=32,
                unique=True,
            ),
        ),
    ]
