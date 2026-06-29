from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("provider", "0004_provider_declined_jobs"),
    ]

    operations = [
        migrations.AddField(
            model_name="provideronboarding",
            name="nid_extracted_data",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "OCR fields transcribed from the National ID by AI validation "
                    "(nid_number, name_on_nid, dob_on_nid, address_on_nid, issue_date, "
                    "expiry_date). Stored separately so it stays queryable."
                ),
            ),
        ),
    ]
