import uuid

from django.contrib.gis.db import models
from django.core.validators import MinValueValidator
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .choices import CancelledBy, ServiceRequestStatus


class ServiceRequest(models.Model):
    """
    Core transaction model for the platform.

    State Flow:
        pending -> assigned -> confirmed -> in_progress -> completed
        assigned -> declined (back to pending for admin to reassign)
        cancelled (from any non-terminal state)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # --- Parties ---
    customer = models.ForeignKey(
        "customer.Customer",
        on_delete=models.PROTECT,
        related_name="service_requests",
    )
    provider = models.ForeignKey(
        "provider.Provider",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_requests",
    )

    # --- What & Where ---
    category = models.ForeignKey(
        "core.Category",
        on_delete=models.PROTECT,
        related_name="service_requests",
    )
    region = models.ForeignKey(
        "core.Region",
        on_delete=models.PROTECT,
        related_name="service_requests",
    )
    address = models.TextField(help_text="Exact service address")
    location = models.PointField(
        geography=True,
        srid=4326,
        help_text="Exact pin-drop location (longitude, latitude)",
    )
    floor_number = models.CharField(
        max_length=20,
        help_text="Floor number (e.g. 3, Ground, Basement)",
    )
    apartment_number = models.CharField(
        max_length=20,
        help_text="Apartment or unit number",
    )
    special_mark = models.TextField(
        help_text="Landmark or navigation instructions for the provider",
    )

    # --- Description ---
    title = models.CharField(max_length=200)
    description = models.TextField()
    is_urgent = models.BooleanField(
        default=False,
        help_text="Customer flagged this as urgent",
    )

    # --- Scheduling ---
    preferred_date = models.DateField()
    preferred_time = models.TimeField()

    # --- Pricing ---
    estimated_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Price estimated at booking time",
    )
    final_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Actual price after job completion",
    )

    # --- Status ---
    status = models.CharField(
        max_length=max(len(v) for v in ServiceRequestStatus.values),
        choices=ServiceRequestStatus.choices,
        default=ServiceRequestStatus.PENDING,
        db_index=True,
    )

    # --- Cancellation ---
    cancelled_by = models.CharField(
        max_length=max(len(v) for v in CancelledBy.values),
        choices=CancelledBy.choices,
        blank=True,
    )
    cancellation_reason = models.TextField(blank=True)

    # --- Decline ---
    decline_reason = models.TextField(blank=True)

    # --- Admin Notes ---
    admin_notes = models.TextField(
        blank=True,
        help_text="Internal notes (not visible to customer/provider)",
    )

    # --- Timestamps ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "service_requests"
        verbose_name = "Service Request"
        verbose_name_plural = "Service Requests"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["provider", "status"]),
            models.Index(fields=["region", "category", "status"]),
            models.Index(fields=["preferred_date", "status"]),
        ]

    def __str__(self):
        return f"#{str(self.id)[:8].upper()} | {self.category} | {self.get_status_display()}"

    # ── FSM Guard Checks ──────────────────────────────────────

    def can_assign(self):
        return self.status == ServiceRequestStatus.PENDING

    def can_confirm(self):
        return self.status == ServiceRequestStatus.ASSIGNED

    def can_start(self):
        return self.status == ServiceRequestStatus.CONFIRMED

    def can_complete(self):
        return self.status == ServiceRequestStatus.IN_PROGRESS

    def can_cancel(self):
        return self.status not in (
            ServiceRequestStatus.COMPLETED,
            ServiceRequestStatus.CANCELLED,
        )

    def can_decline(self):
        return self.status == ServiceRequestStatus.ASSIGNED

    # ── FSM Transitions ───────────────────────────────────────

    @transaction.atomic
    def assign(self, provider):
        """Admin assigns a provider. Transitions: pending → assigned."""
        if not self.can_assign():
            raise ValueError(
                f"Cannot assign from '{self.get_status_display()}' status."
            )
        self.provider = provider
        self.status = ServiceRequestStatus.ASSIGNED
        self.assigned_at = timezone.now()
        self.save(update_fields=["provider", "status", "assigned_at", "updated_at"])
        provider.__class__.objects.filter(pk=provider.pk).update(
            total_jobs=F("total_jobs") + 1
        )

    @transaction.atomic
    def self_assign(self, provider):
        """Provider picks a pending request from the open pool.

        Transitions: pending → assigned.
        Guard: provider must have no active (assigned/confirmed/in_progress) jobs.
        Uses select_for_update to prevent two providers grabbing the same request.
        """
        # Re-fetch with a row lock to prevent race conditions
        obj = ServiceRequest.objects.select_for_update().get(pk=self.pk)
        if obj.status != ServiceRequestStatus.PENDING:
            raise ValueError("This request is no longer available.")

        active_statuses = [
            ServiceRequestStatus.ASSIGNED,
            ServiceRequestStatus.CONFIRMED,
            ServiceRequestStatus.IN_PROGRESS,
        ]
        has_active = ServiceRequest.objects.filter(
            provider=provider, status__in=active_statuses
        ).exists()
        if has_active:
            raise ValueError(
                "You already have an active job. "
                "Complete or cancel it before picking a new one."
            )

        obj.provider = provider
        obj.status = ServiceRequestStatus.ASSIGNED
        obj.assigned_at = timezone.now()
        obj.save(update_fields=["provider", "status", "assigned_at", "updated_at"])

        provider.__class__.objects.filter(pk=provider.pk).update(
            total_jobs=F("total_jobs") + 1
        )
        # Sync the in-memory instance so the caller gets fresh data
        self.refresh_from_db()

    def confirm(self):
        """Provider accepts the assignment. Transitions: assigned → confirmed."""
        if not self.can_confirm():
            raise ValueError(
                f"Cannot confirm from '{self.get_status_display()}' status."
            )
        self.status = ServiceRequestStatus.CONFIRMED
        self.confirmed_at = timezone.now()
        self.save(update_fields=["status", "confirmed_at", "updated_at"])

    def start(self):
        """Provider starts work. Transitions: confirmed → in_progress."""
        if not self.can_start():
            raise ValueError(f"Cannot start from '{self.get_status_display()}' status.")
        self.status = ServiceRequestStatus.IN_PROGRESS
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at", "updated_at"])

    @transaction.atomic
    def complete(self, final_price=None):
        """Provider completes the job. Transitions: in_progress → completed."""
        if not self.can_complete():
            raise ValueError(
                f"Cannot complete from '{self.get_status_display()}' status."
            )
        update_fields = ["status", "completed_at", "updated_at"]
        if final_price is not None:
            self.final_price = final_price
            update_fields.append("final_price")
        self.status = ServiceRequestStatus.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=update_fields)

        if self.provider_id:
            self.provider.__class__.objects.filter(pk=self.provider_id).update(
                completed_jobs=F("completed_jobs") + 1,
                total_earnings=F("total_earnings") + (self.final_price or 0),
                available_balance=F("available_balance") + (self.final_price or 0),
            )
        self.customer.__class__.objects.filter(pk=self.customer_id).update(
            total_bookings=F("total_bookings") + 1
        )

    @transaction.atomic
    def cancel(self, cancelled_by, reason=""):
        """Cancel the request. Transitions: any non-terminal → cancelled."""
        if not self.can_cancel():
            raise ValueError(f"Cannot cancel a '{self.get_status_display()}' request.")
        # Roll back provider job count if they were already involved
        if self.provider_id and self.status in (
            ServiceRequestStatus.ASSIGNED,
            ServiceRequestStatus.CONFIRMED,
            ServiceRequestStatus.IN_PROGRESS,
        ):
            self.provider.__class__.objects.filter(pk=self.provider_id).update(
                total_jobs=F("total_jobs") - 1
            )
        self.status = ServiceRequestStatus.CANCELLED
        self.cancelled_by = cancelled_by
        self.cancellation_reason = reason
        self.cancelled_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "cancelled_by",
                "cancellation_reason",
                "cancelled_at",
                "updated_at",
            ]
        )

    @transaction.atomic
    def decline(self, reason=""):
        """Provider declines the assignment. Transitions: assigned → pending.

        The request goes back to the pool for admin to reassign to another provider.
        """
        if not self.can_decline():
            raise ValueError(
                f"Cannot decline from '{self.get_status_display()}' status."
            )
        if self.provider_id:
            self.provider.__class__.objects.filter(pk=self.provider_id).update(
                total_jobs=F("total_jobs") - 1
            )
        self.status = ServiceRequestStatus.PENDING
        self.provider = None
        self.assigned_at = None
        self.decline_reason = reason
        self.declined_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "provider",
                "assigned_at",
                "decline_reason",
                "declined_at",
                "updated_at",
            ]
        )


class Review(models.Model):
    """
    One review per completed service request, written by the customer.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_request = models.OneToOneField(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name="review",
    )
    customer = models.ForeignKey(
        "customer.Customer",
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    provider = models.ForeignKey(
        "provider.Provider",
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1)],
        help_text="1-5 stars",
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reviews"
        verbose_name = "Review"
        verbose_name_plural = "Reviews"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1) & models.Q(rating__lte=5),
                name="rating_1_to_5",
            )
        ]

    def __str__(self):
        return f"Review #{str(self.service_request_id)[:8]} — {self.rating}★"
