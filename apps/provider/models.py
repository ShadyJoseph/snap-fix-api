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
    message="Phone number must be a valid Egyptian mobile number (e.g., 01012345678 or +201012345678)."
)


class Provider(User):
    """Provider model for service providers"""

    # Verification
    verification_status = models.CharField(
        max_length=max(len(choice[0])
                       for choice in ProviderVerificationStatus.choices),
        choices=ProviderVerificationStatus.choices,
        default=ProviderVerificationStatus.PENDING
    )
    id_document = models.FileField(
        upload_to='provider_documents/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
        help_text="ID document for verification (Max 5MB)"
    )
    certification = models.FileField(
        upload_to='provider_certifications/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
        help_text="Professional certifications (Max 5MB)"
    )

    # Service Information
    categories = models.ManyToManyField(
        'core.Category',
        related_name='providers',
        blank=True,
        help_text="Service categories this provider operates in"
    )
    region = models.ForeignKey(
        'core.Region',
        on_delete=models.PROTECT,
        related_name='providers',
        null=True,
        blank=True,
        help_text="Primary region where provider operates"
    )

    # Business Information
    business_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Business or company name"
    )
    bio = models.TextField(
        blank=True,
        help_text="Brief description about services"
    )
    years_of_experience = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Years of professional experience"
    )

    # Financial
    hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(0)],
        help_text="Hourly rate"
    )
    total_earnings = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0)],
        help_text="Total earnings from all jobs"
    )
    available_balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0)],
        help_text="Balance available for withdrawal"
    )

    # Availability
    is_available = models.BooleanField(
        default=True,
        help_text="Currently available for jobs"
    )
    service_radius = models.IntegerField(
        default=10,
        validators=[MinValueValidator(0)],
        help_text="Service radius in kilometers"
    )

    # Statistics
    total_jobs = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Total number of jobs received"
    )
    completed_jobs = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Total number of completed jobs"
    )
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0)],
        help_text="Average rating from reviews"
    )
    total_reviews = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Total number of reviews received"
    )

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
        """Validate file sizes"""
        super().clean()
        if self.id_document and self.id_document.size > 5 * 1024 * 1024:
            raise ValidationError({
                'id_document': 'File size must not exceed 5MB'
            })
        if self.certification and self.certification.size > 5 * 1024 * 1024:
            raise ValidationError({
                'certification': 'File size must not exceed 5MB'
            })

    def add_earnings(self, amount):
        """Add earnings from a completed job"""
        if amount > 0:
            self.total_earnings += amount
            self.available_balance += amount
            self.save(update_fields=['total_earnings', 'available_balance'])

    def withdraw_balance(self, amount):
        """Withdraw available balance if sufficient"""
        if amount > 0 and self.available_balance >= amount:
            self.available_balance -= amount
            self.save(update_fields=['available_balance'])
            return True
        return False

    def increment_jobs(self):
        """Increment total jobs counter"""
        self.total_jobs += 1
        self.save(update_fields=['total_jobs'])

    def increment_completed_jobs(self):
        """Increment completed jobs counter"""
        self.completed_jobs += 1
        self.save(update_fields=['completed_jobs'])

    def get_completion_rate(self):
        """Calculate job completion rate as percentage"""
        if self.total_jobs == 0:
            return 0
        return round((self.completed_jobs / self.total_jobs) * 100, 2)

    def update_rating(self, new_rating):
        """Update average rating with a new rating"""
        if 0 <= new_rating <= 5:
            total_rating = self.average_rating * self.total_reviews
            self.total_reviews += 1
            self.average_rating = (
                total_rating + new_rating) / self.total_reviews
            self.save(update_fields=['average_rating', 'total_reviews'])


class ProviderOnboarding(models.Model):
    """
    Provider onboarding application with FSM workflow

    State Flow:
    pending -> under_review -> approved/rejected/changes_required
    changes_required -> under_review -> approved/rejected
    """

    # Primary Key
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Personal Information
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True, db_index=True)
    phone = models.CharField(
        max_length=20,
        validators=[phone_validator]
    )
    date_of_birth = models.DateField(help_text="Date of birth")

    # Address Information
    address = models.TextField()
    region = models.ForeignKey(
        'core.Region',
        on_delete=models.PROTECT,
        related_name='onboarding_applications',
        help_text="Region where provider will operate"
    )

    # Service Information
    category = models.ForeignKey(
        'core.Category',
        on_delete=models.PROTECT,
        related_name='onboarding_applications',
        help_text="Service category"
    )
    hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Initial hourly rate"
    )
    years_of_experience = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Years of experience in this field"
    )
    bio = models.TextField(
        blank=True,
        help_text="Brief description of services and experience"
    )

    # Documents
    nid_front = models.ImageField(
        upload_to='onboarding/nid/front/',
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
        help_text="National ID - Front side (Max 5MB)"
    )
    nid_back = models.ImageField(
        upload_to='onboarding/nid/back/',
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
        help_text="National ID - Back side (Max 5MB)"
    )
    police_clearance_certificate = models.FileField(
        upload_to='onboarding/pcc/',
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
        help_text="Police Clearance Certificate (Max 5MB)"
    )
    professional_certificate = models.FileField(
        upload_to='onboarding/certificates/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'pdf'])],
        help_text="Professional certificates - optional (Max 5MB)"
    )
    profile_photo = models.ImageField(
        upload_to='onboarding/photos/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png'])],
        help_text="Profile photo - optional (Max 5MB)"
    )

    # FSM State
    status = models.CharField(
        max_length=max(len(choice[0]) for choice in OnboardingStatus.choices),
        choices=OnboardingStatus.choices,
        default=OnboardingStatus.PENDING,
        db_index=True
    )

    # Admin Actions & Notes
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_onboardings',
        help_text="Admin who reviewed this application"
    )
    admin_notes = models.TextField(
        blank=True,
        help_text="Internal notes from admin"
    )
    rejection_reason = models.TextField(
        blank=True,
        help_text="Reason for rejection"
    )
    change_requests = models.TextField(
        blank=True,
        help_text="Specific changes requested"
    )

    # Created Provider
    provider = models.OneToOneField(
        Provider,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='onboarding_application',
        help_text="Provider account created after approval"
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
        return f"{self.first_name} {self.last_name} - {self.get_status_display()}"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def age(self):
        """Calculate age from date of birth"""
        today = date.today()
        born = self.date_of_birth
        return today.year - born.year - (
            (today.month, today.day) < (born.month, born.day)
        )

    def clean(self):
        """Model-level validation"""
        super().clean()

        # Validate age
        if self.date_of_birth and self.age < 18:
            raise ValidationError({
                'date_of_birth': 'Applicant must be 18 or older'
            })

        # Check email uniqueness across User model
        if not self.pk:  # Only on creation
            if User.objects.filter(email=self.email).exists():
                raise ValidationError({
                    'email': 'This email is already registered in the system.'
                })

        # Validate file sizes
        files = [
            ('nid_front', self.nid_front),
            ('nid_back', self.nid_back),
            ('police_clearance_certificate', self.police_clearance_certificate),
            ('professional_certificate', self.professional_certificate),
            ('profile_photo', self.profile_photo),
        ]

        for field_name, file_field in files:
            if file_field and hasattr(file_field, 'size'):
                if file_field.size > 5 * 1024 * 1024:  # 5MB
                    raise ValidationError({
                        field_name: 'File size must not exceed 5MB'
                    })

    # FSM State Checks
    def can_review(self):
        return self.status in [
            OnboardingStatus.PENDING,
            OnboardingStatus.CHANGES_REQUIRED
        ]

    def can_approve(self):
        return self.status == OnboardingStatus.UNDER_REVIEW

    def can_reject(self):
        return self.status == OnboardingStatus.UNDER_REVIEW

    def can_request_changes(self):
        return self.status == OnboardingStatus.UNDER_REVIEW

    # FSM State Transitions
    def move_to_review(self, admin_user):
        """Transition to under_review state"""
        if not self.can_review():
            raise ValueError(
                f"Cannot move to review from {self.get_status_display()}"
            )

        self.status = OnboardingStatus.UNDER_REVIEW
        self.reviewed_by = admin_user
        self.reviewed_at = timezone.now()
        self.save()
        return True

    @transaction.atomic
    def approve(self, admin_user):
        """Approve application and create provider account"""
        if not self.can_approve():
            raise ValueError(
                f"Cannot approve from {self.get_status_display()}"
            )

        # Generate temporary password
        from django.utils.crypto import get_random_string
        temp_password = get_random_string(12)

        # Create Provider account using create_user
        provider = Provider.objects.create_user(
            email=self.email,
            password=temp_password,
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

        # Transfer documents to provider
        if self.nid_front:
            provider.id_document = self.nid_front
        if self.professional_certificate:
            provider.certification = self.professional_certificate
        if self.profile_photo:
            provider.profile_picture = self.profile_photo

        provider.save()

        # Add category
        provider.categories.add(self.category)

        # Link provider
        self.provider = provider
        self.status = OnboardingStatus.APPROVED
        self.reviewed_by = admin_user
        self.approved_at = timezone.now()
        self.save()

        return provider

    def reject(self, admin_user, reason):
        """Reject application"""
        if not self.can_reject():
            raise ValueError(
                f"Cannot reject from {self.get_status_display()}"
            )

        self.status = OnboardingStatus.REJECTED
        self.reviewed_by = admin_user
        self.rejection_reason = reason
        self.rejected_at = timezone.now()
        self.save()

        return True

    def request_changes(self, admin_user, change_requests):
        """Request changes to application"""
        if not self.can_request_changes():
            raise ValueError(
                f"Cannot request changes from {self.get_status_display()}"
            )

        self.status = OnboardingStatus.CHANGES_REQUIRED
        self.reviewed_by = admin_user
        self.change_requests = change_requests
        self.reviewed_at = timezone.now()
        self.save()

        return True
