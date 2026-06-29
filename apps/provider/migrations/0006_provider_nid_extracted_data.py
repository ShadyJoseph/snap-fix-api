from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("provider", "0005_provideronboarding_nid_extracted_data"),
    ]

    operations = [
        migrations.AddField(
            model_name="provider",
            name="nid_extracted_data",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "NID OCR fields captured from the AI validation at approval time "
                    "(copied from the onboarding application). Verified identity record."
                ),
            ),
        ),
    ]
