import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("provider", "0002_provideronboarding_onboarding_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="AIValidationLog",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "triggered_at",
                    models.DateTimeField(auto_now_add=True, db_index=True),
                ),
                (
                    "applicant_snapshot",
                    models.JSONField(
                        default=dict,
                        help_text="Name, DOB, and phone captured at call time.",
                    ),
                ),
                (
                    "documents_sent",
                    models.JSONField(
                        default=list,
                        help_text="List of document labels that were included in the API call.",
                    ),
                ),
                (
                    "outcome",
                    models.CharField(
                        choices=[
                            ("passed", "Passed"),
                            ("flagged", "Flagged"),
                            ("failed", "Failed"),
                            ("bypassed", "Bypassed (flag off)"),
                            ("error", "Error"),
                        ],
                        db_index=True,
                        max_length=10,
                    ),
                ),
                (
                    "raw_response",
                    models.TextField(
                        blank=True,
                        help_text="Raw text returned by Claude before JSON parsing.",
                    ),
                ),
                (
                    "parsed_report",
                    models.JSONField(
                        default=dict,
                        help_text="Parsed and status-enriched report stored on the onboarding row.",
                    ),
                ),
                (
                    "error_message",
                    models.TextField(
                        blank=True,
                        help_text="Exception or fallback reason when outcome is 'error'.",
                    ),
                ),
                (
                    "model_id",
                    models.CharField(
                        blank=True,
                        help_text="Claude model identifier used for this call.",
                        max_length=100,
                    ),
                ),
                (
                    "latency_ms",
                    models.IntegerField(
                        blank=True,
                        help_text="Wall-clock time from API call start to response, in milliseconds.",
                        null=True,
                    ),
                ),
                ("input_tokens", models.IntegerField(blank=True, null=True)),
                ("output_tokens", models.IntegerField(blank=True, null=True)),
                (
                    "onboarding",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_validation_logs",
                        to="provider.provideronboarding",
                    ),
                ),
            ],
            options={
                "verbose_name": "AI Validation Log",
                "verbose_name_plural": "AI Validation Logs",
                "ordering": ["-triggered_at"],
            },
        ),
    ]
