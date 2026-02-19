import uuid
from datetime import date

from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models, transaction
from django.utils import timezone

from apps.user.models import User

from .choices import OnboardingStatus, ProviderVerificationStatus
from .managers import ProviderOnboardingManager

phone_validator = RegexValidator(
    regex=r'^(\+?20)?01[0125]\d{8}$',
    message="Must be a valid Egyptian mobile number (e.g., 01012345678 or +201012345678)."
)

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


class Provider(User):
    """Service provider — created only via onboarding approval."""

    verification_status = models.CharField(
        max_length=max(len(c[0]) for c in ProviderVerificationStatus.choices),
        choices=ProviderVerificationStatus.choices,
        default=ProviderVerificationStatus.PENDING,
        db_index=True,
    )
    id_document = models.FileField(
        upload_to='provider_documents/',
        blank=True, null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
        help_text="ID document (Max 5MB)",
    )
    certification = models.FileField(
        upload_to='provider_certifications/',
        blank=True, null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
        help_text="Professional certifications (Max 5MB)",
    )

    # Service
    categories = models.ManyToManyField(
        'core.Category',
        related_name='providers',
        blank=True,
    )
    region = models.ForeignKey(
        'core.Region',
        on_delete=models.PROTECT,
        related_name='providers',
        null=True, blank=True,
    )

    # Business
    business_name = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    years_of_experience = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )
    hourly_rate = models.DecimalField(
        max_digits=10, decimal_places=2,
        blank=True, null=True,
        validators=[MinValueValidator(0)],
    )

    # Financial
    total_earnings = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0)],
    )
    available_balance = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0)],
    )

    # Availability
    is_available = models.BooleanField(default=True)
    service_radius = models.IntegerField(
        default=10,
        validators=[MinValueValidator(0)],
        help_text="Service radius in kilometers",
    )

    # Statistics
    total_jobs = models.IntegerField(
        default=0, validators=[MinValueValidator(0)])
    completed_jobs = models.IntegerField(
        default=0, validators=[MinValueValidator(0)])
    average_rating = models.DecimalField(
        max_digits=3, decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0)],
    )
    total_reviews = models.IntegerField(
        default=0, validators=[MinValueValidator(0)])

    class Meta:
        db_table = 'providers'
        verbose_name = 'Provider'
        verbose_name_plural = 'Providers'
        indexes = [
            models.Index(fields=['verification_status']),
            models.Index(fields=['is_available']),
            models.Index(fields=['region', 'is_available']),
        ]

    def __str__(self):
        return f"Provider: {self.get_full_name()}"

    def clean(self):
        super().clean()
        for field in ('id_document', 'certification'):
            f = getattr(self, field)
            if f and hasattr(f, 'size') and f.size > MAX_FILE_SIZE:
                raise ValidationError(
                    {field: 'File size must not exceed 5MB.'})

    # ── Financial helpers ────────────────────────────────────

    def add_earnings(self, amount):
        if amount > 0:
            self.total_earnings += amount
            self.available_balance += amount
            self.save(update_fields=['total_earnings', 'available_balance'])

    def withdraw_balance(self, amount):
        if amount > 0 and self.available_balance >= amount:
            self.available_balance -= amount
            self.save(update_fields=['available_balance'])
            return True
        return False

    # ── Stats helpers ────────────────────────────────────────

    def increment_jobs(self):
        self.total_jobs += 1
        self.save(update_fields=['total_jobs'])

    def increment_completed_jobs(self):
        self.completed_jobs += 1
        self.save(update_fields=['completed_jobs'])

    def get_completion_rate(self):
        if self.total_jobs == 0:
            return 0
        return round((self.completed_jobs / self.total_jobs) * 100, 2)

    def update_rating(self, new_rating):
        if 0 <= new_rating <= 5:
            total = self.average_rating * self.total_reviews
            self.total_reviews += 1
            self.average_rating = (total + new_rating) / self.total_reviews
            self.save(update_fields=['average_rating', 'total_reviews'])


class ProviderOnboarding(models.Model):
    """
    Onboarding application with FSM workflow.

    State flow:
        pending → under_review → approved / rejected / changes_required
        changes_required → under_review → approved / rejected
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Personal
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True, db_index=True)
    phone = models.CharField(max_length=20, validators=[phone_validator])
    date_of_birth = models.DateField()

    # Location
    address = models.TextField()
    region = models.ForeignKey(
        'core.Region',
        on_delete=models.PROTECT,
        related_name='onboarding_applications',
    )

    # Service
    category = models.ForeignKey(
        'core.Category',
        on_delete=models.PROTECT,
        related_name='onboarding_applications',
    )
    hourly_rate = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    years_of_experience = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )
    bio = models.TextField(blank=True)

    # Documents
    nid_front = models.ImageField(
        upload_to='onboarding/nid/front/',
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
    )
    nid_back = models.ImageField(
        upload_to='onboarding/nid/back/',
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
    )
    police_clearance_certificate = models.FileField(
        upload_to='onboarding/pcc/',
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
    )
    professional_certificate = models.FileField(
        upload_to='onboarding/certificates/',
        blank=True, null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
    )
    profile_photo = models.ImageField(
        upload_to='onboarding/photos/',
        blank=True, null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png'])],
    )

    # FSM
    status = models.CharField(
        max_length=max(len(c[0]) for c in OnboardingStatus.choices),
        choices=OnboardingStatus.choices,
        default=OnboardingStatus.PENDING,
        db_index=True,
    )

    # Review
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reviewed_onboardings',
    )
    admin_notes = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    change_requests = models.TextField(blank=True)

    # Result
    provider = models.OneToOneField(
        Provider,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='onboarding_application',
    )

    # Timestamps
    submitted_at = models.DateTimeField(default=timezone.now)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProviderOnboardingManager()

    class Meta:
        db_table = 'provider_onboarding'
        verbose_name = 'Provider Onboarding Application'
        verbose_name_plural = 'Provider Onboarding Applications'
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['status', '-submitted_at']),
            models.Index(fields=['email']),
            models.Index(fields=['region', 'category', 'status']),
        ]

    def __str__(self):
        return f"{self.get_full_name()} — {self.get_status_display()}"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def age(self):
        today = date.today()
        born = self.date_of_birth
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

    def clean(self):
        super().clean()

        if self.date_of_birth and self.age < 18:
            raise ValidationError(
                {'date_of_birth': 'Applicant must be 18 or older.'})

        # Email uniqueness against User table — only on first creation
        if not self.pk and User.objects.filter(email=self.email).exists():
            raise ValidationError(
                {'email': 'This email is already registered.'})

        # File size validation
        file_fields = [
            'nid_front', 'nid_back', 'police_clearance_certificate',
            'professional_certificate', 'profile_photo',
        ]
        for field_name in file_fields:
            f = getattr(self, field_name)
            if f and hasattr(f, 'size') and f.size > MAX_FILE_SIZE:
                raise ValidationError(
                    {field_name: 'File size must not exceed 5MB.'})

    # ── FSM Guards ───────────────────────────────────────────

    def can_review(self):
        return self.status in (OnboardingStatus.PENDING, OnboardingStatus.CHANGES_REQUIRED)

    def can_approve(self):
        return self.status == OnboardingStatus.UNDER_REVIEW

    def can_reject(self):
        return self.status == OnboardingStatus.UNDER_REVIEW

    def can_request_changes(self):
        return self.status == OnboardingStatus.UNDER_REVIEW

    # ── FSM Transitions ──────────────────────────────────────

    def move_to_review(self, admin_user):
        if not self.can_review():
            raise ValueError(
                f"Cannot move to Under Review from '{self.get_status_display()}'.")
        self.status = OnboardingStatus.UNDER_REVIEW
        self.reviewed_by = admin_user
        self.reviewed_at = timezone.now()
        self.save()

    @transaction.atomic
    def approve(self, admin_user, password):
        """Approve and create the Provider account. Password must be provided explicitly."""
        if not self.can_approve():
            raise ValueError(
                f"Cannot approve from '{self.get_status_display()}'.")

        # Guard against duplicate email at approval time
        if User.objects.filter(email=self.email).exists():
            raise ValueError(
                f"Email '{self.email}' is already registered. "
                "This person may already have a customer or staff account."
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

        if self.nid_front:
            provider.id_document = self.nid_front
        if self.professional_certificate:
            provider.certification = self.professional_certificate
        if self.profile_photo:
            provider.profile_picture = self.profile_photo

        provider.save()
        provider.categories.add(self.category)

        self.provider = provider
        self.status = OnboardingStatus.APPROVED
        self.reviewed_by = admin_user
        self.approved_at = timezone.now()
        self.save()

        return provider

    def reject(self, admin_user, reason):
        if not self.can_reject():
            raise ValueError(
                f"Cannot reject from '{self.get_status_display()}'.")
        self.status = OnboardingStatus.REJECTED
        self.reviewed_by = admin_user
        self.rejection_reason = reason
        self.rejected_at = timezone.now()
        self.save()

    def request_changes(self, admin_user, change_requests):
        if not self.can_request_changes():
            raise ValueError(
                f"Cannot request changes from '{self.get_status_display()}'.")
        self.status = OnboardingStatus.CHANGES_REQUIRED
        self.reviewed_by = admin_user
        self.change_requests = change_requests
        self.reviewed_at = timezone.now()
        self.save()
