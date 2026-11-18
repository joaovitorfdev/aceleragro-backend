from django.contrib import admin

from acelera_agro.documents.models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "original_filename",
        "proposal",
        "detected_kind",
        "extraction_status",
        "created_at",
    )
    list_filter = ("detected_kind", "extraction_status")
    search_fields = ("original_filename", "s3_key")
