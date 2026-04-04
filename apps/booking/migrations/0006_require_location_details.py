"""
Migration 0006 — Require location details on ServiceRequest.

Strategy:
  1. RunPython: backfill `location` for any existing rows that lack it.
     Priority: use the request's region centre; fall back to Cairo centre.
  2. RunPython: backfill `floor_number` / `apartment_number` / `special_mark`
     with safe placeholder values so no row has an empty string after migration.
  3. AlterField: remove null/blank from `location` (enforces NOT NULL at DB level).
  4. AlterField: remove blank from the three text detail fields
     (enforces non-empty via Django model validation / admin).
"""

import django.contrib.gis.db.models.fields
from django.contrib.gis.geos import Point
from django.db import migrations, models

# Default fallback coordinates — Cairo city centre.
_CAIRO = Point(31.2357, 30.0444, srid=4326)

# Placeholder values written to legacy rows that have no data.
_FLOOR_PLACEHOLDER = "N/A"
_APT_PLACEHOLDER = "N/A"
_MARK_PLACEHOLDER = "No additional instructions"


def backfill_location(apps, schema_editor):
    """Set `location` on every row that currently has NULL."""
    ServiceRequest = apps.get_model("booking", "ServiceRequest")

    missing = list(
        ServiceRequest.objects.filter(location__isnull=True).select_related("region")
    )
    if not missing:
        return

    for sr in missing:
        region_point = (
            sr.region.location
            if sr.region_id and sr.region.location is not None
            else None
        )
        sr.location = region_point if region_point is not None else _CAIRO

    ServiceRequest.objects.bulk_update(missing, ["location"])


def backfill_detail_fields(apps, schema_editor):
    """Replace empty strings in the three new text fields with placeholders."""
    ServiceRequest = apps.get_model("booking", "ServiceRequest")
    ServiceRequest.objects.filter(floor_number="").update(
        floor_number=_FLOOR_PLACEHOLDER
    )
    ServiceRequest.objects.filter(apartment_number="").update(
        apartment_number=_APT_PLACEHOLDER
    )
    ServiceRequest.objects.filter(special_mark="").update(
        special_mark=_MARK_PLACEHOLDER
    )


class Migration(migrations.Migration):
    # RunPython ops UPDATE the PostGIS geography column, queuing deferred triggers.
    # AlterField on the same table then fails with "pending trigger events" inside
    # a single transaction. atomic=False lets each operation commit independently.
    atomic = False

    dependencies = [
        ("booking", "0005_remove_servicerequest_latitude_and_more"),
    ]

    operations = [
        # 1. Backfill before we tighten the constraints.
        migrations.RunPython(backfill_location, migrations.RunPython.noop),
        migrations.RunPython(backfill_detail_fields, migrations.RunPython.noop),
        # 2. Make `location` NOT NULL at the database level.
        migrations.AlterField(
            model_name="servicerequest",
            name="location",
            field=django.contrib.gis.db.models.fields.PointField(
                geography=True,
                help_text="Exact pin-drop location (longitude, latitude)",
                srid=4326,
            ),
        ),
        # 3. Remove blank=True from the detail text fields so Django model
        #    validation (admin, forms) treats them as required too.
        migrations.AlterField(
            model_name="servicerequest",
            name="floor_number",
            field=models.CharField(
                max_length=20,
                help_text="Floor number (e.g. 3, Ground, Basement)",
            ),
        ),
        migrations.AlterField(
            model_name="servicerequest",
            name="apartment_number",
            field=models.CharField(
                max_length=20,
                help_text="Apartment or unit number",
            ),
        ),
        migrations.AlterField(
            model_name="servicerequest",
            name="special_mark",
            field=models.TextField(
                help_text="Landmark or navigation instructions for the provider",
            ),
        ),
    ]
