import uuid

from django.contrib.gis.db import models
from django.contrib.gis.geos import Point


class Category(models.Model):
    """Service categories that providers can operate in."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=10, blank=True, help_text="Emoji icon e.g. 🔧")
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0, help_text="Display order")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "categories"
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        ordering = ["order", "name"]

    def __str__(self):
        return f"{self.icon} {self.name}".strip()


class Region(models.Model):
    """Geographic regions where providers operate."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    code = models.CharField(
        max_length=20, unique=True, help_text="Region code (e.g., CAI, ALX)"
    )
    country = models.CharField(max_length=100, default="Egypt")

    # PostGIS Point — replaces separate lat/lng fields
    location = models.PointField(
        geography=True,
        null=True,
        blank=True,
        help_text="Region center point (longitude, latitude)",
        srid=4326,
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "regions"
        verbose_name = "Region"
        verbose_name_plural = "Regions"
        ordering = ["country", "name"]
        indexes = [
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.name}, {self.country}"

    @property
    def latitude(self):
        return self.location.y if self.location else None

    @property
    def longitude(self):
        return self.location.x if self.location else None

    @classmethod
    def set_location(cls, lat, lng):
        """Helper to create a Point from lat/lng."""
        return Point(x=lng, y=lat, srid=4326)


class Office(models.Model):
    """Physical office locations."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=500, help_text="Full string address")
    landmark = models.CharField(
        max_length=200,
        blank=True,
        help_text="Nearby famous place e.g. 'Next to Cairo Tower'",
    )
    location = models.PointField(
        geography=True,
        null=True,
        blank=True,
        srid=4326,
        help_text="Exact coordinates (longitude, latitude)",
    )
    region = models.ForeignKey(
        Region,
        on_delete=models.PROTECT,
        related_name="offices",
    )
    working_hours = models.CharField(
        max_length=200,
        help_text="e.g. 'Sun–Thu 9:00 AM – 5:00 PM'",
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "offices"
        verbose_name = "Office"
        verbose_name_plural = "Offices"
        ordering = ["region", "name"]

    def __str__(self):
        return f"{self.name} — {self.region.name}"

    @property
    def latitude(self):
        return self.location.y if self.location else None

    @property
    def longitude(self):
        return self.location.x if self.location else None
