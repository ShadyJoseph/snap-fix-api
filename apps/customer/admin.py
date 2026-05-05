from django.contrib import admin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "first_name",
        "last_name",
        "wallet_balance",
        "total_bookings",
        "is_active",
        "date_joined",
    )
    list_filter = ("is_active", "is_verified", "date_joined")
    search_fields = ("email", "first_name", "last_name", "phone")
    ordering = ("-date_joined",)
    readonly_fields = (
        "date_joined",
        "last_login",
        "updated_at",
        "total_cashback",
        "total_bookings",
        "location",
    )
    filter_horizontal = ("favorite_providers",)

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
                )
            },
        ),
        ("Location", {"fields": ("address", "location")}),
        ("Wallet & Finances", {"fields": ("wallet_balance", "total_cashback")}),
        ("Favorites", {"fields": ("favorite_providers",)}),
        ("Statistics", {"fields": ("total_bookings",)}),
        ("Status", {"fields": ("is_active", "is_verified")}),
        (
            "Timestamps",
            {
                "fields": ("date_joined", "last_login", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("favorite_providers")
