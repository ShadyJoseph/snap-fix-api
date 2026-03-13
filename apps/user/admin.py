from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "email",
        "first_name",
        "last_name",
        "get_user_type",
        "is_active",
        "date_joined",
    )
    list_filter = ("is_active", "is_verified", "is_staff")
    search_fields = ("email", "first_name", "last_name", "phone")
    ordering = ("-date_joined",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Personal Info",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "phone",
                    "profile_picture",
                    "address",
                ),
            },
        ),
        ("Location", {"fields": ("latitude", "longitude")}),
        (
            "Permissions",
            {
                "fields": ("is_active", "is_staff", "is_superuser", "is_verified"),
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "first_name",
                    "last_name",
                ),
            },
        ),
    )

    def has_add_permission(self, request):
        # Users are created through Customer, Provider, or Staff — never directly
        return False

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj and hasattr(obj, "staff"):
            # is_staff is app-controlled for Staff instances — set automatically by Staff.save()
            if "is_staff" not in readonly:
                readonly.append("is_staff")
        return readonly

    @admin.display(description="User Type")
    def get_user_type(self, obj):
        return obj.get_user_type()
