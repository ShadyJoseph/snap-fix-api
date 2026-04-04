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
    readonly_fields = ("date_joined", "last_login", "updated_at", "total_cashback", "location")
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

    def get_queryset(self, request):
        """Optimize queries with prefetch_related for favorites"""
        qs = super().get_queryset(request)
        return qs.prefetch_related("favorite_providers")
