from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.core.validators import (
    FileExtensionValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models, transaction
from django.utils import timezone

from apps.staff.models import Staff
from apps.user.models import User

from .choices import OnboardingStatus, ProviderVerificationStatus
from .managers import ProviderManager, ProviderOnboardingManager

phone_validator = RegexValidator(
    regex=r"^(\+?20)?01[0125]\d{8}$",
    message="Must be a valid Egyptian mobile number (e.g., 01012345678 or +201012345678).",
)

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


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

    def update_rating(self, new_rating: float) -> None:
        if 0 <= new_rating <= 5:
            total = self.average_rating * self.total_reviews
            self.total_reviews += 1
            self.average_rating = (total + new_rating) / self.total_reviews
            self.save(update_fields=["average_rating", "total_reviews"])


class ProviderOnboarding(models.Model):
    """
    Onboarding application filled by staff at the office.
    Single source of truth for all provider documents.

    State machine
    -------------
    pending → under_review → approved
                           → rejected
                           → changes_required → under_review (repeat)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Pre-registered provider who came via the mobile app.
    # NULL for walk-ins who have no prior account.
    applicant = models.OneToOneField(
        Provider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pending_application",
    )

    # Personal details — editable by staff at the office
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True, db_index=True)
    phone = models.CharField(max_length=20, validators=[phone_validator])
    date_of_birth = models.DateField()
    address = models.TextField()

    region = models.ForeignKey(
        "core.Region",
        on_delete=models.PROTECT,
        related_name="onboarding_applications",
    )
    category = models.ForeignKey(
        "core.Category",
        on_delete=models.PROTECT,
        related_name="onboarding_applications",
    )
    hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
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

    # Review state
    status = models.CharField(
        max_length=max(len(c[0]) for c in OnboardingStatus.choices),
        choices=OnboardingStatus.choices,
        default=OnboardingStatus.PENDING,
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

        if self.date_of_birth and self.age < 18:
            raise ValidationError({"date_of_birth": "Applicant must be 18 or older."})

        # staff could link applicant_A to an onboarding with
        # email_B, then approve() would activate the wrong provider account.
        # Enforce that the applicant FK always matches the onboarding email.
        if self.applicant_id and self.applicant and self.applicant.email != self.email:
            raise ValidationError(
                {
                    "applicant": (
                        f"Applicant email ({self.applicant.email}) does not match "
                        f"the application email ({self.email}). "
                        "Update the email field to match the applicant, "
                        "or clear the applicant selection for a walk-in."
                    )
                }
            )

        # On create only: block duplicate emails unless it belongs to a
        # pending (not-yet-activated) provider who is completing onboarding.
        if not self.pk and User.objects.filter(email=self.email).exists():
            is_pending_provider = Provider.objects.filter(
                email=self.email,
                is_active=False,
                verification_status=ProviderVerificationStatus.PENDING,
            ).exists()
            if not is_pending_provider:
                raise ValidationError({"email": "This email is already registered."})

        # File size guard — only validate fresh uploads; skip stored paths to
        # avoid FileNotFoundError on ephemeral filesystems (e.g. Railway).
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
                if f.size > MAX_FILE_SIZE:
                    raise ValidationError(
                        {field_name: "File size must not exceed 5 MB."}
                    )
            except (FileNotFoundError, OSError):
                pass

    # ── FSM guards ────────────────────────────────────────────────────────────

    def can_review(self) -> bool:
        return self.status in (
            OnboardingStatus.PENDING,
            OnboardingStatus.CHANGES_REQUIRED,
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
    def approve(
        self, admin_user: Staff | None, password: str | None = None
    ) -> Provider:
        """
        Approve the application and activate the provider account.

        Two paths
        ---------
        Pre-registered (applicant is set)
            Activate the existing inactive Provider without creating a new row.
        Walk-in (no applicant)
            Create a brand-new Provider account; password is required.

        The caller (save_model) must save form data first and call
        refresh_from_db() before invoking this method so that self reflects
        the latest database state.
        """
        if not self.can_approve():
            raise ValueError(f"Cannot approve from '{self.status}'.")

        # filter by is_active=False so an already-active user
        # (admin, client, staff) with the same email is never matched.
        # The applicant FK is the authoritative link; this fallback only fires
        # when the FK was not set at onboarding creation time.
        existing_user = (
            self.applicant
            if self.applicant_id
            else User.objects.filter(email=self.email, is_active=False).first()
        )

        if existing_user is not None:
            if not hasattr(existing_user, "provider"):
                raise ValueError(
                    f"'{self.email}' exists but is not a provider account."
                )
            provider = existing_user.provider
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
        else:
            if not password:
                raise ValueError(
                    "Password is required when no prior registration exists."
                )
            provider = Provider.objects.create_user(
                email=self.email,
                password=password,
                first_name=self.first_name,
                last_name=self.last_name,
                phone=self.phone,
                address=self.address,
                region=self.region,
                hourly_rate=self.hourly_rate,
                years_of_experience=self.years_of_experience,
                bio=self.bio,
                verification_status=ProviderVerificationStatus.VERIFIED,
                is_verified=True,
                is_active=True,
            )
            provider.categories.add(self.category)

        # Save only FSM/audit fields — form data was already saved by save_model
        self.provider = provider
        self.status = OnboardingStatus.APPROVED
        self.reviewed_by = admin_user
        self.approved_at = timezone.now()
        self.save(update_fields=["provider", "status", "reviewed_by", "approved_at"])

        return provider

    def reject(self, admin_user: Staff | None, reason: str) -> None:
        if not self.can_reject():
            raise ValueError(f"Cannot reject from '{self.status}'.")
        self.status = OnboardingStatus.REJECTED
        self.reviewed_by = admin_user
        self.rejection_reason = reason
        self.rejected_at = timezone.now()
        self.save()

    def request_changes(self, admin_user: Staff | None, change_requests: str) -> None:
        if not self.can_request_changes():
            raise ValueError(f"Cannot request changes from '{self.status}'.")
        self.status = OnboardingStatus.CHANGES_REQUIRED
        self.reviewed_by = admin_user
        self.change_requests = change_requests
        self.reviewed_at = timezone.now()
        self.save()
