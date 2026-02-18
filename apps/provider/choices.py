from django.db import models


class ProviderVerificationStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    VERIFIED = 'verified', 'Verified'
    REJECTED = 'rejected', 'Rejected'


class OnboardingStatus(models.TextChoices):
    PENDING = 'pending', 'Pending Review'
    UNDER_REVIEW = 'under_review', 'Under Review'
    CHANGES_REQUIRED = 'changes_required', 'Changes Required'
    APPROVED = 'approved', 'Approved'
    REJECTED = 'rejected', 'Rejected'
