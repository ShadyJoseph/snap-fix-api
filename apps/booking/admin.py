import logging

from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from .choices import CancelledBy, ServiceRequestStatus
from .models import ServiceRequest

logger = logging.getLogger(__name__)


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    """Admin interface for ServiceRequest with FSM workflow."""

    list_display = (
        "short_id",
        "customer_name",
        "provider_name",
        "category",
        "region",
        "status_badge",
        "is_urgent",
        "preferred_date",
        "final_price",
        "created_at",
    )
    list_filter = (
        "status",
        "is_urgent",
        "category",
        "region",
        "preferred_date",
        "created_at",
    )
    search_fields = (
        "id",
        "title",
        "customer__email",
        "customer__first_name",
        "customer__last_name",
        "provider__email",
        "provider__first_name",
        "provider__last_name",
    )
    # customer/provider are MTI models — raw_id_fields avoids autocomplete
    # resolution issues with inherited tables.
    raw_id_fields = ("customer", "provider")
    autocomplete_fields = ("category", "region")
    readonly_fields = (
        "id",
        "status",
        "assigned_at",
        "confirmed_at",
        "started_at",
        "completed_at",
        "cancelled_at",
        "created_at",
        "updated_at",
        "customer_link",
        "provider_link",
        "cancellation_info",
    )
    add_fieldsets = (
        (
            "Parties",
            {
                "fields": ("customer", "provider"),
            },
        ),
        (
            "Request Details",
            {
                "fields": ("title", "description", "category", "is_urgent"),
            },
        ),
        (
            "Location & Scheduling",
            {
                "fields": (
                    "region",
                    "address",
                    "latitude",
                    "longitude",
                    "preferred_date",
                    "preferred_time",
                ),
            },
        ),
        (
            "Pricing",
            {
                "fields": ("estimated_price", "final_price"),
            },
        ),
        (
            "Admin Notes",
            {
                "fields": ("admin_notes",),
            },
        ),
    )
    fieldsets = (
        (
            "Status",
            {
                "fields": ("id", "status", "customer_link", "provider_link"),
            },
        ),
        (
            "Request Details",
            {
                "fields": ("title", "description", "category", "is_urgent"),
            },
        ),
        (
            "Location & Scheduling",
            {
                "fields": (
                    "region",
                    "address",
                    "latitude",
                    "longitude",
                    "preferred_date",
                    "preferred_time",
                ),
            },
        ),
        (
            "Pricing",
            {
                "fields": ("estimated_price", "final_price"),
            },
        ),
        (
            "Cancellation",
            {
                "fields": ("cancellation_info",),
                "classes": ("collapse",),
            },
        ),
        (
            "Admin Notes",
            {
                "fields": ("admin_notes",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "assigned_at",
                    "confirmed_at",
                    "started_at",
                    "completed_at",
                    "cancelled_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )
    actions = [
        "action_confirm",
        "action_start",
        "action_complete",
        "action_cancel_by_admin",
    ]

    def get_fieldsets(self, request, obj=None):
        """Use add_fieldsets on create, fieldsets on edit."""
        if obj is None:
            return self.add_fieldsets
        return self.fieldsets

    def get_readonly_fields(self, request, obj=None):
        """Make provider readonly if not PENDING to prevent inconsistencies."""
        if obj and obj.status != ServiceRequestStatus.PENDING:
            return self.readonly_fields + ("provider",)
        return self.readonly_fields

    # Display helpers

    @admin.display(description="ID")
    def short_id(self, obj):
        return str(obj.id)[:8].upper()

    @admin.display(description="Customer")
    def customer_name(self, obj):
        return obj.customer.get_full_name() if obj.customer_id else "—"

    @admin.display(description="Provider")
    def provider_name(self, obj):
        return obj.provider.get_full_name() if obj.provider_id else "—"

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            ServiceRequestStatus.PENDING: "#FFA500",
            ServiceRequestStatus.ASSIGNED: "#2196F3",
            ServiceRequestStatus.CONFIRMED: "#9C27B0",
            ServiceRequestStatus.IN_PROGRESS: "#FF9800",
            ServiceRequestStatus.COMPLETED: "#4CAF50",
            ServiceRequestStatus.CANCELLED: "#F44336",
        }
        return format_html(
            '<span style="background:{};color:white;padding:3px 10px;border-radius:10px;'
            'font-weight:bold;font-size:10px;text-transform:uppercase;letter-spacing:0.5px">{}</span>',
            colors.get(obj.status, "#757575"),
            obj.get_status_display(),
        )

    @admin.display(description="Customer")
    def customer_link(self, obj):
        if not obj.pk or not obj.customer_id:
            return "—"
        url = reverse("admin:customer_customer_change", args=[obj.customer_id])
        return format_html(
            '<a href="{}">{} ({})</a>',
            url,
            obj.customer.get_full_name(),
            obj.customer.email,
        )

    @admin.display(description="Provider")
    def provider_link(self, obj):
        if not obj.pk or not obj.provider_id:
            return "—"
        url = reverse("admin:provider_provider_change", args=[obj.provider_id])
        return format_html(
            '<a href="{}">{} ({})</a>',
            url,
            obj.provider.get_full_name(),
            obj.provider.email,
        )

    @admin.display(description="Cancellation Details")
    def cancellation_info(self, obj):
        if obj.status != ServiceRequestStatus.CANCELLED:
            return "—"
        return format_html(
            "<strong>Cancelled by:</strong> {}<br><strong>Reason:</strong> {}",
            obj.get_cancelled_by_display() or "—",
            obj.cancellation_reason or "—",
        )

    # Query optimisation

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("customer", "provider", "category", "region")
        )

    # Admin actions

    def _run_transition(
        self, request, queryset, transition_fn, past_tense, allowed_statuses
    ):
        """Generic FSM transition runner for bulk actions."""
        success_count = skip_count = 0
        for obj in queryset:
            if obj.status not in allowed_statuses:
                skip_count += 1
                continue
            try:
                transition_fn(obj)
                success_count += 1
            except Exception as exc:
                logger.error("Transition failed for %s: %s", obj.pk, exc, exc_info=True)
                self.message_user(
                    request, f"Error on #{str(obj.pk)[:8]}: {exc}", messages.ERROR
                )
        if success_count:
            self.message_user(
                request, f"{success_count} request(s) {past_tense}.", messages.SUCCESS
            )
        if skip_count:
            self.message_user(
                request,
                f"{skip_count} request(s) skipped (wrong status).",
                messages.WARNING,
            )

    @admin.action(description="Mark as Confirmed")
    def action_confirm(self, request, queryset):
        self._run_transition(
            request,
            queryset,
            lambda obj: obj.confirm(),
            "confirmed",
            [ServiceRequestStatus.ASSIGNED],
        )

    @admin.action(description="Mark as In Progress")
    def action_start(self, request, queryset):
        self._run_transition(
            request,
            queryset,
            lambda obj: obj.start(),
            "started",
            [ServiceRequestStatus.CONFIRMED],
        )

    @admin.action(description="Mark as Completed")
    def action_complete(self, request, queryset):
        self._run_transition(
            request,
            queryset,
            lambda obj: obj.complete(),
            "completed",
            [ServiceRequestStatus.IN_PROGRESS],
        )

    @admin.action(description="Cancel (Admin)")
    def action_cancel_by_admin(self, request, queryset):
        self._run_transition(
            request,
            queryset,
            lambda obj: obj.cancel(
                cancelled_by=CancelledBy.ADMIN, reason="Cancelled by admin"
            ),
            "cancelled",
            [
                ServiceRequestStatus.PENDING,
                ServiceRequestStatus.ASSIGNED,
                ServiceRequestStatus.CONFIRMED,
                ServiceRequestStatus.IN_PROGRESS,
            ],
        )

    # Save model — handles provider assignment via FSM

    def save_model(self, request, obj, form, change):
        """
        Handles provider assignment via FSM on both create and change.
        Saves the model normally, then if provider is set and status is PENDING,
        routes through FSM assign() to update status, timestamps, and counters.
        """
        super().save_model(request, obj, form, change)
        if obj.status == ServiceRequestStatus.PENDING and obj.provider_id:
            try:
                obj.assign(obj.provider)
                self.message_user(
                    request,
                    f"Provider {obj.provider.get_full_name()} assigned successfully.",
                    messages.SUCCESS,
                )
            except Exception as exc:
                self.message_user(request, str(exc), messages.ERROR)
