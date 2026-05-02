import uuid

from django.contrib.gis.db import models
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .choices import (
    AIRecommendationOutcome,
    BookingMode,
    CancelledBy,
    PaymentMethod,
    PaymentStatus,
    ServiceRequestStatus,
    max_length,
)


class ServiceRequest(models.Model):
    """
    Core transaction model for the platform.

    State Flow:
        pending → assigned → quoted → confirmed → in_progress → completed
        quoted  → pending  (customer rejects quote)
        assigned → pending (provider declines)
        cancelled (from any non-terminal state)

    Payment flow:
        • Customer picks payment_method + wallet_amount at request creation.
        • wallet_amount is re-validated at quote approval.
        • Payment is settled at completion:
            - Wallet portion: deducted from customer wallet.
            - CARD remainder: Stripe PaymentIntent captured.
            - CASH remainder: honor-system; provider collects in person.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ── Parties ───────────────────────────────────────────────

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

    # ── What & Where ──────────────────────────────────────────

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
        help_text="Landmark or navigation instructions for the provider"
    )

    # ── Description ───────────────────────────────────────────

    title = models.CharField(max_length=200)
    description = models.TextField()
    is_urgent = models.BooleanField(
        default=False,
        help_text="Customer flagged this as urgent",
    )

    # ── Scheduling ────────────────────────────────────────────

    preferred_date = models.DateField()
    preferred_time = models.TimeField()

    # ── Pricing ───────────────────────────────────────────────

    estimated_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Customer's rough estimate at booking time (informational only)",
    )
    quoted_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Price submitted by the provider",
    )
    final_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Locked from quoted_price when customer approves. "
        "This is the single authoritative amount due.",
    )

    # ── Payment ───────────────────────────────────────────────

    payment_method = models.CharField(
        max_length=max_length(PaymentMethod),
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
        help_text=(
            "How the non-wallet portion is paid. "
            "WALLET = full amount from wallet; "
            "CASH = remainder collected by provider; "
            "CARD = remainder charged via Stripe."
        ),
    )
    wallet_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text=(
            "Amount the customer pre-commits to pay from their wallet. "
            "Must be ≤ final_price. Can be 0 (no wallet used)."
        ),
    )
    payment_status = models.CharField(
        max_length=max_length(PaymentStatus),
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
    )
    # Stripe PaymentIntent ID — populated when card payment is initiated.
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Stripe PaymentIntent ID for card payments",
    )

    # ── Status & Audit ────────────────────────────────────────

    status = models.CharField(
        max_length=max_length(ServiceRequestStatus),
        choices=ServiceRequestStatus.choices,
        default=ServiceRequestStatus.PENDING,
        db_index=True,
    )
    cancelled_by = models.CharField(
        max_length=max_length(CancelledBy),
        choices=CancelledBy.choices,
        blank=True,
    )
    cancellation_reason = models.TextField(blank=True)
    decline_reason = models.TextField(blank=True)
    admin_notes = models.TextField(blank=True)
    booking_mode = models.CharField(
        max_length=max_length(BookingMode),
        choices=BookingMode.choices,
        default=BookingMode.BROADCAST,
        db_index=True,
    )

    # ── Timestamps ────────────────────────────────────────────

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
        return (
            f"#{str(self.id)[:8].upper()} | {self.category} | "
            f"{self.get_status_display()}"
        )

    # ── Derived helpers ───────────────────────────────────────

    @property
    def card_amount(self):
        """Amount to be charged to the card (final_price - wallet_amount)."""
        if self.final_price is None:
            return None
        return max(self.final_price - (self.wallet_amount or 0), 0)

    def _validate_wallet_funds(self, amount, error_message):
        """
        Helper method to lock the customer and validate wallet balance.
        Should be called within a transaction.atomic block.
        """
        if amount <= 0:
            return None
        locked_customer = self.customer.__class__.objects.select_for_update().get(
            pk=self.customer_id
        )
        if locked_customer.wallet_balance < amount:
            raise ValueError(
                f"{error_message} "
                f"Required: {amount}, available: {locked_customer.wallet_balance}."
            )
        return locked_customer

    # ── FSM Guards ────────────────────────────────────────────

    def can_assign(self):
        return self.status == ServiceRequestStatus.PENDING

    def can_quote(self):
        return self.status == ServiceRequestStatus.ASSIGNED

    def can_approve_quote(self):
        return self.status == ServiceRequestStatus.QUOTED

    def can_reject_quote(self):
        return self.status == ServiceRequestStatus.QUOTED

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
        """Admin assigns a provider. pending → assigned."""
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
        """Provider picks a request from the open pool. pending → assigned."""
        obj = ServiceRequest.objects.select_for_update().get(pk=self.pk)
        if obj.status != ServiceRequestStatus.PENDING:
            raise ValueError("This request is no longer available.")

        active_statuses = [
            ServiceRequestStatus.ASSIGNED,
            ServiceRequestStatus.QUOTED,
            ServiceRequestStatus.CONFIRMED,
            ServiceRequestStatus.IN_PROGRESS,
        ]
        if ServiceRequest.objects.filter(
            provider=provider, status__in=active_statuses
        ).exists():
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
        self.refresh_from_db()

    def quote(self, price):
        """Provider submits their price. assigned → quoted."""
        if not self.can_quote():
            raise ValueError(f"Cannot quote from '{self.get_status_display()}' status.")
        self.quoted_price = price
        self.status = ServiceRequestStatus.QUOTED
        self.save(update_fields=["quoted_price", "status", "updated_at"])

    @transaction.atomic
    def approve_quote(self):
        """
        Customer approves the quoted price. quoted → confirmed.

        Locks quoted_price → final_price.
        Re-validates wallet_amount against the now-known final price and
        the customer's current balance.

        Raises ValueError if wallet funds are insufficient — caller must
        redirect the customer to adjust their payment split.
        """
        if not self.can_approve_quote():
            raise ValueError(
                f"Cannot approve quote from '{self.get_status_display()}' status."
            )

        self.final_price = self.quoted_price

        # Re-validate wallet portion now that the real price is known.
        wallet_amount = self.wallet_amount or 0
        if wallet_amount > 0:
            if wallet_amount > self.final_price:
                raise ValueError(
                    f"Wallet amount ({wallet_amount}) exceeds the quoted price "
                    f"({self.final_price}). Please adjust your payment."
                )
            self._validate_wallet_funds(
                wallet_amount,
                "Insufficient wallet balance. Please reduce your wallet contribution or switch payment method.",
            )

        self.status = ServiceRequestStatus.CONFIRMED
        self.confirmed_at = timezone.now()
        self.save(
            update_fields=[
                "final_price",
                "status",
                "confirmed_at",
                "updated_at",
            ]
        )

    @transaction.atomic
    def reject_quote(self):
        """Customer rejects the price. quoted → pending (back to pool)."""
        if not self.can_reject_quote():
            raise ValueError(
                f"Cannot reject quote from '{self.get_status_display()}' status."
            )
        self.provider.__class__.objects.filter(pk=self.provider_id).update(
            total_jobs=F("total_jobs") - 1
        )
        self.status = ServiceRequestStatus.PENDING
        self.provider = None
        self.assigned_at = None
        self.quoted_price = None
        self.save(
            update_fields=[
                "status",
                "provider",
                "assigned_at",
                "quoted_price",
                "updated_at",
            ]
        )

    @transaction.atomic
    def confirm(self):
        """Provider skips quote and accepts directly. assigned → confirmed."""
        if not self.can_confirm():
            raise ValueError(
                f"Cannot confirm from '{self.get_status_display()}' status."
            )

        self.final_price = self.estimated_price

        # Re-validate wallet portion against the now-set final price.
        wallet_amount = self.wallet_amount or 0
        if wallet_amount > 0:
            if wallet_amount > self.final_price:
                wallet_amount = self.final_price
                self.wallet_amount = wallet_amount

            self._validate_wallet_funds(
                wallet_amount,
                "Customer has insufficient wallet balance for this price. Please submit a quote instead.",
            )

        self.status = ServiceRequestStatus.CONFIRMED
        self.confirmed_at = timezone.now()
        self.save(
            update_fields=[
                "final_price",
                "wallet_amount",
                "status",
                "confirmed_at",
                "updated_at",
            ]
        )

    def start(self):
        """Provider starts work. confirmed → in_progress."""
        if not self.can_start():
            raise ValueError(f"Cannot start from '{self.get_status_display()}' status.")
        self.status = ServiceRequestStatus.IN_PROGRESS
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at", "updated_at"])

    @transaction.atomic
    def complete(self):
        """
        Provider marks the job done. in_progress → completed.

        Payment is settled here in full:

        1. Wallet portion (wallet_amount):
           - Deducted from customer balance with a row lock.
           - If balance is now insufficient, raises ValueError (should not
             happen if approve_quote() validated correctly, but guards against
             race conditions / manual balance changes).

        2. Card portion (final_price - wallet_amount):
           - If payment_method == CARD: Stripe PaymentIntent is captured.
           - If payment_method == CASH: honor-system; provider collects cash.

        3. Provider balances are updated only once everything succeeds.
        """
        if not self.can_complete():
            raise ValueError(
                f"Cannot complete from '{self.get_status_display()}' status."
            )

        final = self.final_price or 0
        wallet_portion = min(self.wallet_amount or 0, final)
        remainder = final - wallet_portion

        # ── Step 1: Deduct wallet ─────────────────────────────
        if wallet_portion > 0:
            locked_customer = self._validate_wallet_funds(
                wallet_portion, "Insufficient wallet balance at completion."
            )
            locked_customer.__class__.objects.filter(pk=self.customer_id).update(
                wallet_balance=F("wallet_balance") - wallet_portion
            )

        # ── Step 2: Settle remainder ──────────────────────────
        if self.payment_method == PaymentMethod.CASH:
            # Provider collects cash directly — platform marks as paid on trust.
            self.payment_status = PaymentStatus.PAID

        elif self.payment_method == PaymentMethod.CARD:
            if remainder > 0:
                self._capture_stripe_payment(remainder)
            self.payment_status = PaymentStatus.PAID

        elif self.payment_method == PaymentMethod.WALLET:
            # Pure wallet — wallet_portion covers everything.
            self.payment_status = PaymentStatus.PAID

        # ── Step 3: Finalise request ──────────────────────────
        self.status = ServiceRequestStatus.COMPLETED
        self.completed_at = timezone.now()
        self.save(
            update_fields=["status", "completed_at", "payment_status", "updated_at"]
        )

        # ── Step 4: Credit provider ───────────────────────────
        if self.provider_id:
            # available_balance: wallet & card amounts are platform-collected.
            # Cash remainder goes directly to the provider — not credited here.
            platform_collected = wallet_portion + (
                remainder if self.payment_method == PaymentMethod.CARD else 0
            )
            self.provider.__class__.objects.filter(pk=self.provider_id).update(
                completed_jobs=F("completed_jobs") + 1,
                total_earnings=F("total_earnings") + final,
                available_balance=F("available_balance") + platform_collected,
            )

        self.customer.__class__.objects.filter(pk=self.customer_id).update(
            total_bookings=F("total_bookings") + 1
        )

    def _capture_stripe_payment(self, amount):
        """
        Capture the Stripe PaymentIntent for the card portion.
        Uses the test environment only.
        Raises ValueError if capture fails so complete() can abort atomically.
        """
        import stripe
        from django.conf import settings

        stripe.api_key = settings.STRIPE_SECRET_KEY  # test key from settings

        try:
            if not self.stripe_payment_intent_id:
                raise ValueError(
                    "No Stripe PaymentIntent ID found. The customer must initiate "
                    "card payment before the job can be completed."
                )

            # PaymentIntent already created (e.g. during approve_quote).
            # Capture it now that the job is done.
            intent = stripe.PaymentIntent.capture(self.stripe_payment_intent_id)

            if intent.status != "succeeded":
                raise ValueError(
                    f"Stripe payment did not succeed (status: {intent.status})."
                )

            ServiceRequest.objects.filter(pk=self.pk).update(
                stripe_payment_intent_id=intent.id
            )

        except stripe.error.StripeError as exc:
            raise ValueError(f"Card payment failed: {exc.user_message}") from exc

    @transaction.atomic
    def cancel(self, cancelled_by, reason=""):
        """Cancel the request. any non-terminal → cancelled."""
        if not self.can_cancel():
            raise ValueError(f"Cannot cancel a '{self.get_status_display()}' request.")
        if self.provider_id and self.status in (
            ServiceRequestStatus.ASSIGNED,
            ServiceRequestStatus.QUOTED,
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
        """Provider declines the assignment. assigned → pending."""
        if not self.can_decline():
            raise ValueError(
                f"Cannot decline from '{self.get_status_display()}' status."
            )
        if self.provider_id:
            self.provider.__class__.objects.filter(pk=self.provider_id).update(
                total_jobs=F("total_jobs") - 1,
                declined_jobs=F("declined_jobs") + 1,
            )
        self.status = ServiceRequestStatus.PENDING
        self.provider = None
        self.assigned_at = None
        self.decline_reason = reason
        self.declined_at = timezone.now()
        # Re-open declined RECOMMENDED requests as broadcast so they re-enter
        # the open pool instead of sitting stranded (excluded from open pool).
        if self.booking_mode == BookingMode.RECOMMENDED:
            self.booking_mode = BookingMode.BROADCAST
        self.save(
            update_fields=[
                "status",
                "provider",
                "assigned_at",
                "decline_reason",
                "declined_at",
                "booking_mode",
                "updated_at",
            ]
        )


class ServiceRequestPhoto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    image = models.ImageField(
        upload_to="service_requests/photos/",
        validators=[FileExtensionValidator(["jpg", "jpeg", "png"])],
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "service_request_photos"
        ordering = ["uploaded_at"]

    def __str__(self):
        return f"Photo for #{str(self.service_request_id)[:8].upper()}"


class Review(models.Model):
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
        validators=[MinValueValidator(1), MaxValueValidator(5)],
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


class AIRecommendationLog(models.Model):
    """
    Immutable audit log of every AI provider-recommendation call.

    Records the candidate snapshot sent to the AI, the raw and parsed responses,
    latency, and outcome. Mirrors AIValidationLog in apps/provider/models.py.

    service_request is nullable so log rows survive even if the customer abandons
    the flow after receiving recommendations without creating a booking.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_recommendation_logs",
    )
    triggered_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # ── Request context ───────────────────────────────────────────────────────
    category_name = models.CharField(max_length=200, blank=True)
    is_urgent = models.BooleanField(default=False)
    candidate_snapshot = models.JSONField(
        default=list,
        help_text="List of scored candidate dicts (provider id, score, signals) captured at call time.",
    )

    # ── Response ──────────────────────────────────────────────────────────────
    outcome = models.CharField(
        max_length=max_length(AIRecommendationOutcome),
        choices=AIRecommendationOutcome.choices,
        db_index=True,
    )
    raw_response = models.TextField(
        blank=True, help_text="Raw text returned by the AI before JSON parsing."
    )
    parsed_reasons = models.JSONField(
        default=dict,
        help_text="Parsed {provider_id: reason} map returned to the caller.",
    )
    error_message = models.TextField(blank=True)

    # ── Performance ───────────────────────────────────────────────────────────
    model_id = models.CharField(max_length=100, blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "ai_recommendation_logs"
        ordering = ["-triggered_at"]
        verbose_name = "AI Recommendation Log"
        verbose_name_plural = "AI Recommendation Logs"

    def __str__(self):
        return f"[{self.outcome}] {self.category_name} — {self.triggered_at:%Y-%m-%d %H:%M}"
