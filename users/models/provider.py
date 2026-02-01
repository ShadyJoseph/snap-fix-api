from django.db import models

from .user import User


class Provider(User):
    """Provider class inheriting from User"""

    VERIFICATION_STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
    )

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
        help_text="Upload ID document for verification"
    )
    certification = models.FileField(
        upload_to='provider_certifications/',
        blank=True,
        null=True,
        help_text="Upload professional certifications"
    )

    # Business Info
    business_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Business or company name"
    )
    bio = models.TextField(
        blank=True,
        null=True,
        help_text="Brief description about services"
    )
    years_of_experience = models.IntegerField(
        default=0,
        help_text="Years of professional experience"
    )

    # Financial
    hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Hourly rate in USD"
    )
    total_earnings = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Total earnings from all jobs"
    )
    available_balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Balance available for withdrawal"
    )

    # Availability
    is_available = models.BooleanField(
        default=True,
        help_text="Is the provider currently available for jobs?"
    )
    service_radius = models.IntegerField(
        default=10,
        help_text="Service radius in kilometers"
    )

    # Stats
    total_jobs = models.IntegerField(
        default=0,
        help_text="Total number of jobs received"
    )
    completed_jobs = models.IntegerField(
        default=0,
        help_text="Total number of completed jobs"
    )
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.00,
        help_text="Average rating from reviews"
    )
    total_reviews = models.IntegerField(
        default=0,
        help_text="Total number of reviews received"
    )

    class Meta:
        db_table = 'providers'
        verbose_name = 'Provider'
        verbose_name_plural = 'Providers'

    def __str__(self):
        return f"Provider: {self.get_full_name()}"

    def update_rating(self):
        """Update average rating based on reviews"""
        # This will be implemented when Review model is created
        # For now, it's a placeholder
        pass

    def add_earnings(self, amount):
        """Add earnings from a completed job"""
        self.total_earnings += amount
        self.available_balance += amount
        self.save(update_fields=['total_earnings', 'available_balance'])

    def withdraw_balance(self, amount):
        """Withdraw available balance"""
        if self.available_balance >= amount:
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
        """Calculate job completion rate"""
        if self.total_jobs == 0:
            return 0
        return (self.completed_jobs / self.total_jobs) * 100
