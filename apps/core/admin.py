from django.contrib.gis import admin as gis_admin
from django.utils.html import format_html

from .models import Category, Office, Region


@gis_admin.register(Category)
class CategoryAdmin(gis_admin.ModelAdmin):
    list_display = ("icon_display", "name", "slug", "is_active", "order", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("order", "name")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Basic Information", {"fields": ("name", "slug", "description", "icon")}),
        ("Settings", {"fields": ("is_active", "order")}),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    @gis_admin.display(description="Icon")
    def icon_display(self, obj):
        if obj.icon:
            return format_html('<span style="font-size:20px">{}</span>', obj.icon)
        return "—"


@gis_admin.register(Region)
class RegionAdmin(gis_admin.GISModelAdmin):
    list_display = (
        "name",
        "code",
        "country",
        "latitude",
        "longitude",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "country")
    search_fields = ("name", "code", "country")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("country", "name")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Basic Information", {"fields": ("name", "slug", "code", "country")}),
        ("Geographic Data", {"fields": ("location",)}),
        ("Settings", {"fields": ("is_active",)}),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )


@gis_admin.register(Office)
class OfficeAdmin(gis_admin.GISModelAdmin):
    list_display = ("name", "region", "working_hours", "is_active", "created_at")
    list_filter = ("is_active", "region")
    search_fields = ("name", "address", "landmark")
    ordering = ("region", "name")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Basic Information", {"fields": ("name", "region")}),
        ("Location", {"fields": ("address", "landmark", "location")}),
        ("Hours", {"fields": ("working_hours",)}),
        ("Settings", {"fields": ("is_active",)}),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )
