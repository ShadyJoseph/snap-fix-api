from django.contrib import admin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.utils.html import format_html

from .models import Staff


class StaffCreationForm(UserCreationForm):
    """Used on the add page — includes password1/password2 from UserCreationForm."""

    class Meta(UserCreationForm.Meta):
        model = Staff
        fields = (
            "email",
            "first_name",
            "last_name",
            "phone",
            "can_manage_users",
            "can_manage_services",
            "can_manage_payments",
            "can_view_analytics",
        )


class StaffChangeForm(UserChangeForm):
    """Used on the change page — no raw password fields."""

    class Meta(UserChangeForm.Meta):
        model = Staff
        fields = "__all__"


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    form = StaffChangeForm
    add_form = StaffCreationForm

    list_display = (
        "email",
        "first_name",
        "last_name",
        "permissions_summary",
        "is_active",
        "date_joined",
    )
    list_filter = (
        "can_manage_users",
        "can_manage_services",
        "can_manage_payments",
        "can_view_analytics",
        "is_active",
        "is_superuser",
    )
    search_fields = ("email", "first_name", "last_name", "phone")
    readonly_fields = ("is_staff", "date_joined", "last_login", "updated_at")

    fieldsets = (
        (
            "User Information",
            {
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "phone",
                    "profile_picture",
                ),
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "can_manage_users",
                    "can_manage_services",
                    "can_manage_payments",
                    "can_view_analytics",
                ),
            },
        ),
        (
            "Status",
            {
                "fields": ("is_active", "is_staff", "is_superuser"),
                "description": "is_staff is set automatically and cannot be changed manually.",
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("date_joined", "last_login", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    add_fieldsets = (
        (
            "Account",
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "first_name",
                    "last_name",
                    "phone",
                ),
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "can_manage_users",
                    "can_manage_services",
                    "can_manage_payments",
                    "can_view_analytics",
                ),
            },
        ),
    )

    def get_form(self, request, obj=None, **kwargs):
        """Use StaffCreationForm on add, StaffChangeForm on change."""
        if obj is None:
            kwargs["form"] = self.add_form
        return super().get_form(request, obj, **kwargs)

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        return self.fieldsets

    def save_model(self, request, obj, form, change):
        obj.is_staff = True
        super().save_model(request, obj, form, change)

    @admin.display(description="Permissions")
    def permissions_summary(self, obj):
        permissions = []
        if obj.can_manage_users:
            permissions.append("Users")
        if obj.can_manage_services:
            permissions.append("Services")
        if obj.can_manage_payments:
            permissions.append("Payments")
        if obj.can_view_analytics:
            permissions.append("Analytics")

        if not permissions:
            return format_html('<span style="color:gray">No permissions</span>')

        return format_html(
            '<span style="color:green">{}</span>',
            ", ".join(permissions),
        )
