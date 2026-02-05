from django.core.validators import MinValueValidator
from django.db import models

from apps.user.models import User


class Provider(User):
    """Provider model for service providers"""

    VERIFICATION_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
    ]

    # Verification
    verification_status = models.CharField(
        max_length=10,
        choices=VERIFICATION_STATUS_CHOICES,
        default='pending'
    )
    id_document = models.FileField(
        upload_to='provider_documents/',
        blank=True,
        null=True,
        help_text="ID document for verification"
    )
    certification = models.FileField(
        upload_to='provider_certifications/',
        blank=True,
        null=True,
        help_text="Professional certifications"
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
        help_text="Hourly rate in USD"
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
        ]

    def __str__(self):
        return f"Provider: {self.get_full_name()}"

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
