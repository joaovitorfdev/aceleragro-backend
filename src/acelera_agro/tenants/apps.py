from django.apps import AppConfig


class TenantsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "acelera_agro.tenants"
    label = "tenants"
    verbose_name = "Tenants"
