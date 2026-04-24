from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from constance import config
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.core.validators import (
    FileExtensionValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models, transaction
from django.db.models import DecimalField as DecimalOutputField
from django.db.models import ExpressionWrapper, F
from django.utils import timezone

from apps.staff.models import Staff
from apps.user.models import User

from .choices import AIValidationStatus, OnboardingStatus, ProviderVerificationStatus
from .managers import ProviderManager, ProviderOnboardingManager

phone_validator = RegexValidator(
    regex=r"^(\+?20)?01[0125]\d{8}$",
    message="Must be a valid Egyptian mobile number (e.g., 01012345678 or +201012345678).",
)


class Provider(User):
    objects = ProviderManager()

    verification_status = models.CharField(
        max_length=max(len(c[0]) for c in ProviderVerificationStatus.choices),
        choices=ProviderVerificationStatus.choices,
        default=ProviderVerificationStatus.PENDING,
        db_index=True,
    )
    categories = models.ManyToManyField(
        "core.Category",
        related_name="providers",
        blank=True,
    )
    region = models.ForeignKey(
        "core.Region",
        on_delete=models.PROTECT,
        related_name="providers",
        null=True,
        blank=True,
    )
    business_name = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    years_of_experience = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )
    hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(0)],
    )
    total_earnings = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )
    available_balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )
    is_available = models.BooleanField(default=True)
    service_radius = models.IntegerField(
        default=10,
        validators=[MinValueValidator(0)],
        help_text="Service radius in kilometers",
    )
    total_jobs = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    completed_jobs = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0)],
    )
    total_reviews = models.IntegerField(default=0, validators=[MinValueValidator(0)])

    class Meta:
        db_table = "providers"
        verbose_name = "Provider"
        verbose_name_plural = "Providers"
        indexes = [
            models.Index(fields=["verification_status"]),
            models.Index(fields=["is_available"]),
            models.Index(fields=["region", "is_available"]),
        ]

    def __str__(self) -> str:
        return f"Provider: {self.get_full_name()}"

    def add_earnings(self, amount: Decimal) -> None:
        if amount > 0:
            self.total_earnings += amount
            self.available_balance += amount
            self.save(update_fields=["total_earnings", "available_balance"])

    def withdraw_balance(self, amount: Decimal) -> bool:
        if amount > 0 and self.available_balance >= amount:
            self.available_balance -= amount
            self.save(update_fields=["available_balance"])
            return True
        return False

    def get_completion_rate(self) -> float:
        if self.total_jobs == 0:
            return 0
        return round((self.completed_jobs / self.total_jobs) * 100, 2)

    @property
    def rating(self) -> float:
        """Rounded average rating for display on the provider profile."""
        return round(float(self.average_rating), 2)

    def update_rating(self, new_rating: int) -> None:
        """Atomically recalculate average_rating using a single DB UPDATE."""
        if not (1 <= new_rating <= 5):
            return
        Provider.objects.filter(pk=self.pk).update(
            average_rating=ExpressionWrapper(
                (F("average_rating") * F("total_reviews") + new_rating)
                / (F("total_reviews") + 1),
                output_field=DecimalOutputField(max_digits=3, decimal_places=2),
            ),
            total_reviews=F("total_reviews") + 1,
        )
        self.refresh_from_db()


class ProviderOnboarding(models.Model):
    """
    Onboarding application filled by the provider via the mobile app.
    Single source of truth for all provider documents and verification status.

    The provider registers via the mobile app, submits their personal details
    and documents, which creates a DRAFT application. Once submitted, it moves
    to PENDING and is processed by AI, then reviewed by staff.

    State machine
    -------------
    draft → pending → under_review → approved
                                   → rejected
                                   → changes_required → under_review (repeat)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # The pre-registered provider who came via the mobile app.
    # Always required — walk-ins must register via the app first.
    applicant = models.OneToOneField(
        Provider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pending_application",
    )

    # Personal details — submitted by the provider, verified by staff on review
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True, db_index=True)
    phone = models.CharField(max_length=20, validators=[phone_validator])
    # Nullable so a DRAFT can be saved before all required fields are filled.
    # OnboardingSubmitView enforces completeness before moving to PENDING.
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True)

    region = models.ForeignKey(
        "core.Region",
        on_delete=models.PROTECT,
        related_name="onboarding_applications",
        null=True,
        blank=True,
    )
    category = models.ForeignKey(
        "core.Category",
        on_delete=models.PROTECT,
        related_name="onboarding_applications",
        null=True,
        blank=True,
    )
    hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    years_of_experience = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )
    bio = models.TextField(blank=True)

    # Documents
    nid_front = models.ImageField(
        upload_to="onboarding/nid/front/",
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "pdf"])],
    )
    nid_back = models.ImageField(
        upload_to="onboarding/nid/back/",
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "pdf"])],
    )
    police_clearance_certificate = models.FileField(
        upload_to="onboarding/pcc/",
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "pdf"])],
    )
    professional_certificate = models.FileField(
        upload_to="onboarding/certificates/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "pdf"])],
    )
    profile_photo = models.ImageField(
        upload_to="onboarding/photos/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png"])],
    )

    # Review state — starts as DRAFT when the provider self-submits,
    # or PENDING when staff create it directly from the admin.
    status = models.CharField(
        max_length=max(len(c[0]) for c in OnboardingStatus.choices),
        choices=OnboardingStatus.choices,
        default=OnboardingStatus.DRAFT,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        Staff,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_onboardings",
    )
    admin_notes = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    change_requests = models.TextField(blank=True)

    # Set after approval — points to the activated Provider account
    provider = models.OneToOneField(
        Provider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="onboarding_application",
    )

    # AI validation
    ai_validation_status = models.CharField(
        max_length=10,
        choices=AIValidationStatus.choices,
        default=AIValidationStatus.PENDING,
        db_index=True,
    )
    ai_validation_report = models.JSONField(default=dict, blank=True)

    # Resubmission cooldown — set to rejected_at + 30 days on rejection
    can_resubmit_after = models.DateTimeField(null=True, blank=True)

    # Timestamps
    submitted_at = models.DateTimeField(default=timezone.now)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProviderOnboardingManager()

    class Meta:
        db_table = "provider_onboarding"
        verbose_name = "Provider Onboarding Application"
        verbose_name_plural = "Provider Onboarding Applications"
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["status", "-submitted_at"]),
            models.Index(fields=["email"]),
            models.Index(fields=["region", "category", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_full_name()} — {self.status}"

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def age(self) -> int:
        today = date.today()
        born = self.date_of_birth
        return (
            today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        )

    # ── Validation ────────────────────────────────────────────────────────────

    def clean(self) -> None:
        super().clean()

        if self.date_of_birth is not None and self.age < 18:
            raise ValidationError({"date_of_birth": "Applicant must be 18 or older."})

        # Enforce that the applicant FK always matches the onboarding email.
        if self.applicant_id and self.applicant and self.applicant.email != self.email:
            raise ValidationError(
                {
                    "applicant": (
                        f"Applicant email ({self.applicant.email}) does not match "
                        f"the application email ({self.email}). "
                        "Update the email field to match the applicant."
                    )
                }
            )

        # On create: block duplicate emails unless they belong to a PENDING provider
        # completing self-service onboarding (is_active=True since we allow Knox auth).
        if not self.pk and User.objects.filter(email=self.email).exists():
            is_pending_provider = Provider.objects.filter(
                email=self.email,
                verification_status=ProviderVerificationStatus.PENDING,
            ).exists()
            if not is_pending_provider:
                raise ValidationError({"email": "This email is already registered."})

        # File size guard — only validate fresh uploads.
        file_fields = [
            "nid_front",
            "nid_back",
            "police_clearance_certificate",
            "professional_certificate",
            "profile_photo",
        ]
        for field_name in file_fields:
            f = getattr(self, field_name)
            if not f:
                continue
            raw = f.file if hasattr(f, "file") else f
            if not isinstance(raw, UploadedFile):
                continue
            try:
                max_bytes = config.ONBOARDING_MAX_FILE_SIZE_MB * 1024 * 1024
                if f.size > max_bytes:
                    raise ValidationError(
                        {
                            field_name: f"File size must not exceed {config.ONBOARDING_MAX_FILE_SIZE_MB} MB."
                        }
                    )
            except (FileNotFoundError, OSError):
                pass

    # ── FSM guards ────────────────────────────────────────────────────────────

    def can_review(self) -> bool:
        return self.status in (
            OnboardingStatus.PENDING,
            OnboardingStatus.CHANGES_REQUIRED,
        )

    @property
    def can_resubmit(self) -> bool:
        return (
            self.status == OnboardingStatus.REJECTED
            and self.can_resubmit_after is not None
            and timezone.now() >= self.can_resubmit_after
        )

    def can_approve(self) -> bool:
        return self.status == OnboardingStatus.UNDER_REVIEW

    def can_reject(self) -> bool:
        return self.status == OnboardingStatus.UNDER_REVIEW

    def can_request_changes(self) -> bool:
        return self.status == OnboardingStatus.UNDER_REVIEW

    # ── FSM transitions ───────────────────────────────────────────────────────

    def move_to_review(self, admin_user: Staff | None) -> None:
        if not self.can_review():
            raise ValueError(f"Cannot move to Under Review from '{self.status}'.")
        self.status = OnboardingStatus.UNDER_REVIEW
        self.reviewed_by = admin_user
        self.reviewed_at = timezone.now()
        self.save()

    @transaction.atomic
    def approve(self, admin_user: Staff | None) -> Provider:
        """
        Approve the application and activate the provider account.

        Syncs staff-verified fields from the onboarding form onto the provider
        row. The provider's password is never touched — they set it at registration.

        Raises ValueError if the application is not under review, or if no
        pre-registered provider account exists for this email.

        Note: the admin save_model saves form data first and calls refresh_from_db()
        before invoking this method so the latest form values are picked up.
        """
        if not self.can_approve():
            raise ValueError(f"Cannot approve from '{self.status}'.")

        # Prefer the explicit applicant FK (set in self-service flow).
        # Fall back to email lookup for legacy staff-created applications where
        # the FK was not set.
        if self.applicant_id:
            provider = self.applicant
        else:
            provider = Provider.objects.filter(
                email=self.email,
                verification_status=ProviderVerificationStatus.PENDING,
            ).first()
            if provider is None:
                raise ValueError(
                    f"No pre-registered provider found for '{self.email}'. "
                    "The provider must register via the app before approval."
                )

        # Activate and sync reviewed details onto the provider account.
        # Password is never touched — it was set by the provider at registration.
        provider.is_active = True
        provider.is_verified = True
        provider.verification_status = ProviderVerificationStatus.VERIFIED
        provider.first_name = self.first_name
        provider.last_name = self.last_name
        provider.phone = self.phone
        provider.address = self.address
        provider.region = self.region
        provider.hourly_rate = self.hourly_rate
        provider.years_of_experience = self.years_of_experience
        provider.bio = self.bio
        provider.save(
            update_fields=[
                "is_active",
                "is_verified",
                "verification_status",
                "first_name",
                "last_name",
                "phone",
                "address",
                "region",
                "hourly_rate",
                "years_of_experience",
                "bio",
            ]
        )
        provider.categories.add(self.category)

        # Advance FSM — save only audit fields.
        self.provider = provider
        self.status = OnboardingStatus.APPROVED
        self.reviewed_by = admin_user
        self.approved_at = timezone.now()
        self.save(update_fields=["provider", "status", "reviewed_by", "approved_at"])

        return provider

    def reject(self, admin_user: Staff | None, reason: str) -> None:
        if not self.can_reject():
            raise ValueError(f"Cannot reject from '{self.status}'.")
        now = timezone.now()
        self.status = OnboardingStatus.REJECTED
        self.reviewed_by = admin_user
        self.rejection_reason = reason
        self.rejected_at = now
        self.can_resubmit_after = now + timedelta(
            days=config.ONBOARDING_REJECTION_COOLDOWN_DAYS
        )
        self.save()

    def resubmit(self) -> None:
        """Reset a rejected application to DRAFT so the provider can reapply."""
        if not self.can_resubmit:
            raise ValueError(
                "Cannot resubmit: application is not rejected or the "
                "resubmission cooldown has not yet expired."
            )
        self.status = OnboardingStatus.DRAFT
        self.rejection_reason = ""
        self.change_requests = ""
        self.can_resubmit_after = None
        self.ai_validation_status = AIValidationStatus.PENDING
        self.ai_validation_report = {}
        self.reviewed_by = None
        self.reviewed_at = None
        self.rejected_at = None
        self.save()

    def request_changes(self, admin_user: Staff | None, change_requests: str) -> None:
        if not self.can_request_changes():
            raise ValueError(f"Cannot request changes from '{self.status}'.")
        self.status = OnboardingStatus.CHANGES_REQUIRED
        self.reviewed_by = admin_user
        self.change_requests = change_requests
        self.reviewed_at = timezone.now()
        self.save()


# ─────────────────────────────────────────────────────────────────────────────
# AI Validation Log
# ─────────────────────────────────────────────────────────────────────────────


class AIValidationOutcome(models.TextChoices):
    PASSED = "passed", "Passed"
    FLAGGED = "flagged", "Flagged"
    FAILED = "failed", "Failed"
    BYPASSED = "bypassed", "Bypassed (flag off)"
    ERROR = "error", "Error"


class AIValidationLog(models.Model):
    """
    Immutable audit log of every AI validation call made during provider onboarding.

    Records the inputs sent to Claude, the raw and parsed responses, latency,
    token usage, and final outcome. Used for monitoring, debugging, and improving
    the validation pipeline.

    The onboarding FK is nullable so log records survive if an onboarding row
    is deleted (e.g. during cleanup).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    onboarding = models.ForeignKey(
        ProviderOnboarding,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_validation_logs",
    )
    triggered_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # ── Inputs ────────────────────────────────────────────────────────────────
    applicant_snapshot = models.JSONField(
        default=dict,
        help_text="Name, DOB, and phone captured at call time.",
    )
    documents_sent = models.JSONField(
        default=list,
        help_text="List of document labels that were included in the API call.",
    )

    # ── Response ──────────────────────────────────────────────────────────────
    outcome = models.CharField(
        max_length=10,
        choices=AIValidationOutcome.choices,
        db_index=True,
    )
    raw_response = models.TextField(
        blank=True,
        help_text="Raw text returned by Claude before JSON parsing.",
    )
    parsed_report = models.JSONField(
        default=dict,
        help_text="Parsed and status-enriched report stored on the onboarding row.",
    )
    error_message = models.TextField(
        blank=True,
        help_text="Exception or fallback reason when outcome is 'error'.",
    )

    # ── Performance ───────────────────────────────────────────────────────────
    model_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Claude model identifier used for this call.",
    )
    latency_ms = models.IntegerField(
        null=True,
        blank=True,
        help_text="Wall-clock time from API call start to response, in milliseconds.",
    )
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-triggered_at"]
        verbose_name = "AI Validation Log"
        verbose_name_plural = "AI Validation Logs"

    def __str__(self) -> str:
        applicant = self.applicant_snapshot.get("full_name", "unknown")
        return f"[{self.outcome}] {applicant} — {self.triggered_at:%Y-%m-%d %H:%M}"

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is not None and self.output_tokens is not None:
            return self.input_tokens + self.output_tokens
        return None
