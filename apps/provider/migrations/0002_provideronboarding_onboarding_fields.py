import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("provider", "0001_initial"),
    ]

    operations = [
        # ── AI validation fields ──────────────────────────────────────────────
        migrations.AddField(
            model_name="provideronboarding",
            name="ai_validation_report",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="provideronboarding",
            name="ai_validation_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending Validation"),
                    ("running", "Running"),
                    ("passed", "Passed"),
                    ("flagged", "Flagged \u2014 Needs Review"),
                    ("failed", "Failed"),
                ],
                db_index=True,
                default="pending",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="provideronboarding",
            name="can_resubmit_after",
            field=models.DateTimeField(blank=True, null=True),
        ),
        # ── Status: add 'draft' choice and switch default to 'draft' ─────────
        migrations.AlterField(
            model_name="provideronboarding",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("pending", "Pending Review"),
                    ("under_review", "Under Review"),
                    ("changes_required", "Changes Required"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                ],
                db_index=True,
                default="draft",
                max_length=16,
            ),
        ),
        # ── Nullable fields for DRAFT stage ──────────────────────────────────
        migrations.AlterField(
            model_name="provideronboarding",
            name="date_of_birth",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="provideronboarding",
            name="region",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="onboarding_applications",
                to="core.region",
            ),
        ),
        migrations.AlterField(
            model_name="provideronboarding",
            name="category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="onboarding_applications",
                to="core.category",
            ),
        ),
        migrations.AlterField(
            model_name="provideronboarding",
            name="hourly_rate",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        # ── address: TextField blank=True (no DB change; removes required) ───
        migrations.AlterField(
            model_name="provideronboarding",
            name="address",
            field=models.TextField(blank=True),
        ),
    ]
