import logging

from django.contrib import admin, messages
from django.db import transaction
from django.urls import reverse
from django.utils.html import format_html

from apps.notifications import service as notifications

from .choices import (
    AIRecommendationOutcome,
    BookingMode,
    CancelledBy,
    ServiceRequestStatus,
)
from .models import AIRecommendationLog, ServiceRequest, ServiceRequestPhoto

logger = logging.getLogger(__name__)


class ServiceRequestPhotoInline(admin.TabularInline):
    model = ServiceRequestPhoto
    fields = ("image", "uploaded_at")
    readonly_fields = ("uploaded_at",)
    extra = 0
    can_delete = False


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = (
        "short_id",
        "customer_name",
        "provider_name",
        "category",
        "region",
        "status_badge",
        "booking_mode_badge",
        "is_urgent",
        "preferred_date",
        "final_price",
        "payment_method",
        "payment_status",
        "created_at",
    )
    list_filter = (
        "status",
        "booking_mode",
        "payment_method",
        "payment_status",
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
    raw_id_fields = ("customer", "provider")
    autocomplete_fields = ("category", "region")
    readonly_fields = (
        "id",
        "status",
        "booking_mode",
        "location",
        "quoted_price",
        "final_price",
        "payment_status",
        "stripe_payment_intent_id",
        "declined_at",
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
        "payment_summary",
    )
    inlines = [ServiceRequestPhotoInline]
    actions = [
        "action_confirm",
        "action_start",
        "action_complete",
        "action_cancel_by_admin",
    ]

    # ── Fieldsets ─────────────────────────────────────────────

    _pricing_fields = (
        "estimated_price",
        "quoted_price",
        "final_price",
        "payment_method",
        "wallet_amount",
        "payment_summary",
        "payment_status",
        "stripe_payment_intent_id",
    )

    _add_fieldsets = (
        ("Parties", {"fields": ("customer", "provider")}),
        (
            "Request Details",
            {"fields": ("title", "description", "category", "is_urgent")},
        ),
        (
            "Location & Scheduling",
            {
                "fields": (
                    "region",
                    "address",
                    "location",
                    "floor_number",
                    "apartment_number",
                    "special_mark",
                    "preferred_date",
                    "preferred_time",
                )
            },
        ),
        ("Pricing & Payment", {"fields": _pricing_fields}),
        ("Admin Notes", {"fields": ("admin_notes",)}),
    )

    _pending_fieldsets = (
        ("Status", {"fields": ("id", "status", "booking_mode", "customer_link")}),
        (
            "Assign Provider",
            {
                "fields": ("provider",),
                "description": "Select a provider to assign this request.",
            },
        ),
        (
            "Request Details",
            {"fields": ("title", "description", "category", "is_urgent")},
        ),
        (
            "Location & Scheduling",
            {
                "fields": (
                    "region",
                    "address",
                    "location",
                    "floor_number",
                    "apartment_number",
                    "special_mark",
                    "preferred_date",
                    "preferred_time",
                )
            },
        ),
        ("Pricing & Payment", {"fields": _pricing_fields}),
        (
            "Decline Info",
            {"fields": ("decline_reason", "declined_at"), "classes": ("collapse",)},
        ),
        ("Admin Notes", {"fields": ("admin_notes",)}),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    _change_fieldsets = (
        (
            "Status",
            {
                "fields": (
                    "id",
                    "status",
                    "booking_mode",
                    "customer_link",
                    "provider_link",
                )
            },
        ),
        (
            "Request Details",
            {"fields": ("title", "description", "category", "is_urgent")},
        ),
        (
            "Location & Scheduling",
            {
                "fields": (
                    "region",
                    "address",
                    "location",
                    "floor_number",
                    "apartment_number",
                    "special_mark",
                    "preferred_date",
                    "preferred_time",
                )
            },
        ),
        ("Pricing & Payment", {"fields": _pricing_fields}),
        ("Cancellation", {"fields": ("cancellation_info",), "classes": ("collapse",)}),
        (
            "Decline Info",
            {"fields": ("decline_reason", "declined_at"), "classes": ("collapse",)},
        ),
        ("Admin Notes", {"fields": ("admin_notes",)}),
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

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self._add_fieldsets
        if obj.status == ServiceRequestStatus.PENDING:
            return self._pending_fieldsets
        return self._change_fieldsets

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status != ServiceRequestStatus.PENDING:
            return self.readonly_fields + ("provider",)
        return self.readonly_fields

    # ── Display helpers ───────────────────────────────────────

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

    @admin.display(description="Mode")
    def booking_mode_badge(self, obj):
        colors = {
            BookingMode.BROADCAST: "#607D8B",
            BookingMode.DIRECT: "#7B1FA2",
            BookingMode.RECOMMENDED: "#0288D1",
        }
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;border-radius:10px;'
            'font-size:10px;text-transform:uppercase;letter-spacing:0.5px">{}</span>',
            colors.get(obj.booking_mode, "#757575"),
            obj.get_booking_mode_display(),
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

    @admin.display(description="Payment Breakdown")
    def payment_summary(self, obj):
        if obj.final_price is None:
            return "—"
        wallet = obj.wallet_amount or 0
        card = obj.card_amount or 0
        method = obj.get_payment_method_display()
        lines = [f"<strong>Total:</strong> {obj.final_price}"]
        if wallet:
            lines.append(f"<strong>Wallet:</strong> {wallet}")
        if card and obj.payment_method == "card":
            lines.append(f"<strong>Card (Stripe):</strong> {card}")
        elif card and obj.payment_method == "cash":
            lines.append(f"<strong>Cash (provider collects):</strong> {card}")
        lines.append(f"<strong>Method:</strong> {method}")
        return format_html("<br>".join(lines))

    # ── Query optimisation ────────────────────────────────────

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("customer", "provider", "category", "region")
        )

    # ── Save — provider assignment via FSM ────────────────────

    def save_model(self, request, obj, form, change):
        is_pending_with_provider = (
            obj.status == ServiceRequestStatus.PENDING and obj.provider_id
        )
        if is_pending_with_provider:
            provider = obj.provider
            obj.provider = None
            super().save_model(request, obj, form, change)
            try:
                with transaction.atomic():
                    obj.assign(provider)
                    notifications.notify_customer_request_assigned(obj)
                self.message_user(
                    request,
                    f"Provider {provider.get_full_name()} assigned successfully.",
                    messages.SUCCESS,
                )
            except Exception as exc:
                logger.error("Assignment failed for %s: %s", obj.pk, exc, exc_info=True)
                self.message_user(request, str(exc), messages.ERROR)
        else:
            super().save_model(request, obj, form, change)

    # ── Bulk actions ──────────────────────────────────────────

    def _run_transition(
        self, request, queryset, transition_fn, past_tense, allowed_statuses
    ):
        success = skip = 0
        for obj in queryset:
            if obj.status not in allowed_statuses:
                skip += 1
                continue
            try:
                transition_fn(obj)
                success += 1
            except Exception as exc:
                logger.error("Transition failed for %s: %s", obj.pk, exc, exc_info=True)
                self.message_user(
                    request, f"Error on #{str(obj.pk)[:8]}: {exc}", messages.ERROR
                )
        if success:
            self.message_user(
                request, f"{success} request(s) {past_tense}.", messages.SUCCESS
            )
        if skip:
            self.message_user(
                request, f"{skip} request(s) skipped (wrong status).", messages.WARNING
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


# ── AI Recommendation Log Admin ───────────────────────────────────────────────


@admin.register(AIRecommendationLog)
class AIRecommendationLogAdmin(admin.ModelAdmin):
    list_display = (
        "triggered_at",
        "category_name",
        "is_urgent",
        "outcome_badge",
        "model_id",
        "latency_ms",
        "candidates_count",
        "service_request_link",
    )
    list_filter = ("outcome", "model_id", "is_urgent", "triggered_at")
    search_fields = ("category_name", "service_request__id")
    date_hierarchy = "triggered_at"
    ordering = ["-triggered_at"]

    readonly_fields = (
        "id",
        "triggered_at",
        "service_request_link",
        "category_name",
        "is_urgent",
        "outcome_badge",
        "model_id",
        "latency_ms",
        "candidate_snapshot",
        "parsed_reasons",
        "raw_response",
        "error_message",
    )

    fieldsets = (
        (
            "Overview",
            {
                "fields": (
                    "id",
                    "triggered_at",
                    "service_request_link",
                    "category_name",
                    "is_urgent",
                    "outcome_badge",
                ),
            },
        ),
        (
            "Candidates",
            {"fields": ("candidate_snapshot",)},
        ),
        (
            "AI Response",
            {"fields": ("parsed_reasons", "raw_response", "error_message")},
        ),
        (
            "Performance",
            {"fields": ("model_id", "latency_ms")},
        ),
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return request.user.is_superuser

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("service_request")

    @admin.display(description="Outcome")
    def outcome_badge(self, obj):
        colors = {
            AIRecommendationOutcome.SUCCESS: "#4CAF50",
            AIRecommendationOutcome.FALLBACK: "#FF9800",
            AIRecommendationOutcome.BYPASSED: "#9E9E9E",
            AIRecommendationOutcome.ERROR: "#F44336",
        }
        return format_html(
            '<span style="background:{};color:white;padding:3px 10px;'
            "border-radius:10px;font-weight:bold;font-size:10px;"
            'text-transform:uppercase">{}</span>',
            colors.get(obj.outcome, "#757575"),
            obj.get_outcome_display(),
        )

    @admin.display(description="Service Request")
    def service_request_link(self, obj):
        if not obj.service_request_id:
            return format_html(
                '<span style="color:#999;font-style:italic">Unlinked</span>'
            )
        url = reverse(
            "admin:booking_servicerequest_change", args=[obj.service_request_id]
        )
        return format_html(
            '<a href="{}">{}</a>',
            url,
            str(obj.service_request_id)[:8].upper(),
        )

    @admin.display(description="Candidates")
    def candidates_count(self, obj):
        n = len(obj.candidate_snapshot) if obj.candidate_snapshot else 0
        return n
